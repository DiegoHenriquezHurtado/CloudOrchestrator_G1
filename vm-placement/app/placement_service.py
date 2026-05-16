from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.models import Worker, Task, VirtualMachine, Config, User, Slice


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

            # Quota validation
            slice_result = await db.execute(select(Slice).where(Slice.id == task.slice_id))
            slice_obj = slice_result.scalar_one()
            
            user_result = await db.execute(select(User).where(User.id == slice_obj.user_id))
            user_obj = user_result.scalar_one()

            # Calculate total used resources for this user across all their slices
            total_allocated_query = select(
                func.coalesce(func.sum(VirtualMachine.ram), 0),
                func.coalesce(func.sum(VirtualMachine.vcpu), 0)
            ).select_from(VirtualMachine).join(Slice, VirtualMachine.slice_id == Slice.id).where(
                Slice.user_id == user_obj.id,
                Slice.status.notin_(['FAILED', 'DELETED'])
            )
            total_alloc_res = await db.execute(total_allocated_query)
            total_ram_used, total_cpu_used = total_alloc_res.first()

            if total_ram_used > user_obj.quota_ram or total_cpu_used > user_obj.quota_cpu:
                skipped.append({
                    "task_id": task.id,
                    "reason": f"User quota exceeded (RAM: {total_ram_used}/{user_obj.quota_ram}, CPU: {total_cpu_used}/{user_obj.quota_cpu})"
                })
                continue

            selected = None

            # Robust Round Robin using indexed array
            sorted_workers = sorted(workers, key=lambda w: w.id)
            if not sorted_workers:
                skipped.append({"task_id": task.id, "reason": "No workers available in inventory"})
                continue
                
            last_idx = -1
            for idx, w in enumerate(sorted_workers):
                if w.id == last:
                    last_idx = idx
                    break

            reasons = []
            for i in range(1, len(sorted_workers) + 1):
                next_idx = (last_idx + i) % len(sorted_workers)
                wr = sorted_workers[next_idx]

                if wr.status != "ALIVE":
                    reasons.append(f"W{wr.id} status is {wr.status}")
                    continue

                if wr.total_ram == 0:
                    reasons.append(f"W{wr.id} total_ram is 0")
                    continue

                ram_usage = 1 - (
                    wr.current_ram_available / wr.total_ram
                )

                if ram_usage > 0.8:
                    reasons.append(f"W{wr.id} RAM usage {ram_usage:.2f} > 0.8")
                    continue

                current_cpu_load = wr.current_cpu_load if wr.current_cpu_load is not None else 0.0
                available_cpu = wr.total_cpu * (
                    1 - (float(current_cpu_load) / 100.0)
                )

                if wr.current_ram_available < vm.ram:
                    reasons.append(f"W{wr.id} available RAM {wr.current_ram_available} < {vm.ram}")
                    continue

                if available_cpu < vm.vcpu:
                    reasons.append(f"W{wr.id} available CPU {available_cpu:.2f} < {vm.vcpu}")
                    continue

                selected = wr
                break

            if not selected:
                skipped.append({
                    "task_id": task.id,
                    "reason": f"No worker available. Details: {', '.join(reasons)}"
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
