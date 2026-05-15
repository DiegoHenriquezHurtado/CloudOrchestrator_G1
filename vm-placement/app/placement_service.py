from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Worker, Task, VirtualMachine, Config


class PlacementService:

    async def get_last_worker(self, db: AsyncSession):
        result = await db.execute(
            select(Config).where(Config.key == "last_worker_id")
        )
        config = result.scalar_one()
        return int(config.value)

    async def set_last_worker(self, db: AsyncSession, wid: int):
        await db.execute(
            update(Config)
            .where(Config.key == "last_worker_id")
            .values(value=str(wid))
        )

    async def status(self, db: AsyncSession):
        last = await self.get_last_worker(db)

        pending = await db.scalar(
            select(func.count()).where(Task.status == "PENDING")
        )

        ready = await db.scalar(
            select(func.count()).where(Task.status == "PLACEMENT_READY")
        )

        return {
            "last_worker_id": last,
            "tasks_pending": pending,
            "tasks_placement_ready": ready,
            "algorithm": "round_robin"
        }

    async def trigger(self, db: AsyncSession):
        result = await db.execute(
            select(Task).where(Task.status == "PENDING")
        )
        tasks = result.scalars().all()

        assignments = []
        skipped = []

        workers_result = await db.execute(select(Worker))
        workers = workers_result.scalars().all()

        for task in tasks:

            last = await self.get_last_worker(db)

            vm_result = await db.execute(
                select(VirtualMachine).where(
                    VirtualMachine.id == task.vm_id
                )
            )
            vm = vm_result.scalar_one()

            selected = None

            for i in range(len(workers)):
                next_worker = ((last + i) % len(workers)) + 1

                wr = next(w for w in workers if w.id == next_worker)

                if wr.status != "ALIVE":
                    continue

                if wr.total_ram == 0:
                    continue

                ram_usage = 1 - (
                    wr.current_ram_available / wr.total_ram
                )

                if ram_usage > 0.8:
                    continue

                available_cpu = wr.total_cpu * (
                    1 - (wr.current_cpu_load / 100)
                )

                if wr.current_ram_available < vm.ram:
                    continue

                if available_cpu < vm.vcpu:
                    continue

                selected = wr
                break

            if not selected:
                skipped.append({
                    "task_id": task.id,
                    "reason": "No worker available"
                })
                continue

            selected.current_ram_available -= vm.ram
            task.status = "PLACEMENT_READY"
            task.worker_id = selected.id
            vm.worker_id = selected.id

            await self.set_last_worker(db, selected.id)

            assignments.append({
                "task_id": task.id,
                "vm_id": vm.id,
                "worker_id": selected.id,
                "status": "PLACEMENT_READY"
            })

        await db.commit()

        return {
            "tasks_processed": len(assignments),
            "assignments": assignments,
            "skipped": skipped
        }
