#!/usr/bin/env python3
"""
Thread management with proper lifecycle control, monitoring, and graceful shutdown.
"""

import threading
import queue
import time
from typing import Optional, Callable, Any, Dict, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, Future

from PyQt6.QtCore import QThread, pyqtSignal, QObject

from .logging_config import get_logger, log_exception


class TaskPriority(Enum):
    """Task priority levels."""
    LOW = 3
    NORMAL = 2
    HIGH = 1
    CRITICAL = 0


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """Represents a task to be executed."""
    id: str
    name: str
    function: Callable
    args: tuple
    kwargs: dict
    priority: TaskPriority
    callback: Optional[Callable] = None
    error_callback: Optional[Callable] = None
    timeout: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[Exception] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
    
    def __lt__(self, other):
        """For priority queue sorting."""
        return self.priority.value < other.priority.value


class ThreadMonitor:
    """Monitor thread health and performance."""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.active_threads: Dict[str, Dict[str, Any]] = {}
        self.completed_tasks: List[Task] = []
        self.failed_tasks: List[Task] = []
        self._lock = threading.Lock()
        
    def register_thread(self, thread_id: str, thread_name: str):
        """Register a new thread."""
        with self._lock:
            self.active_threads[thread_id] = {
                'name': thread_name,
                'started_at': datetime.now(),
                'last_activity': datetime.now(),
                'tasks_completed': 0,
                'tasks_failed': 0,
                'is_alive': True
            }
    
    def update_thread_activity(self, thread_id: str):
        """Update thread's last activity time."""
        with self._lock:
            if thread_id in self.active_threads:
                self.active_threads[thread_id]['last_activity'] = datetime.now()
    
    def record_task_completion(self, thread_id: str, task: Task):
        """Record successful task completion."""
        with self._lock:
            if thread_id in self.active_threads:
                self.active_threads[thread_id]['tasks_completed'] += 1
            
            self.completed_tasks.append(task)
            
            # Keep only recent history
            if len(self.completed_tasks) > 100:
                self.completed_tasks.pop(0)
    
    def record_task_failure(self, thread_id: str, task: Task):
        """Record task failure."""
        with self._lock:
            if thread_id in self.active_threads:
                self.active_threads[thread_id]['tasks_failed'] += 1
            
            self.failed_tasks.append(task)
            
            # Keep only recent history
            if len(self.failed_tasks) > 50:
                self.failed_tasks.pop(0)
    
    def unregister_thread(self, thread_id: str):
        """Unregister a thread."""
        with self._lock:
            if thread_id in self.active_threads:
                self.active_threads[thread_id]['is_alive'] = False
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get thread pool statistics."""
        with self._lock:
            total_completed = sum(t['tasks_completed'] for t in self.active_threads.values())
            total_failed = sum(t['tasks_failed'] for t in self.active_threads.values())
            
            return {
                'active_threads': len([t for t in self.active_threads.values() if t['is_alive']]),
                'total_threads': len(self.active_threads),
                'tasks_completed': total_completed,
                'tasks_failed': total_failed,
                'success_rate': total_completed / (total_completed + total_failed) if (total_completed + total_failed) > 0 else 0,
                'recent_failures': len(self.failed_tasks),
                'thread_details': dict(self.active_threads)
            }


class WorkerThread(threading.Thread):
    """Worker thread for executing tasks."""
    
    def __init__(self, task_queue: queue.PriorityQueue, monitor: ThreadMonitor, 
                 thread_id: str, shutdown_event: threading.Event):
        super().__init__(daemon=True)
        self.task_queue = task_queue
        self.monitor = monitor
        self.thread_id = thread_id
        self.shutdown_event = shutdown_event
        self.logger = get_logger(__name__)
        self.current_task: Optional[Task] = None
        
    def run(self):
        """Main thread loop."""
        self.monitor.register_thread(self.thread_id, self.name)
        self.logger.info(f"Worker thread {self.thread_id} started")
        
        while not self.shutdown_event.is_set():
            try:
                # Get task with timeout to check shutdown periodically
                try:
                    priority, task = self.task_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                self.current_task = task
                self.monitor.update_thread_activity(self.thread_id)
                
                # Execute task
                self._execute_task(task)
                
                self.task_queue.task_done()
                self.current_task = None
                
            except Exception as e:
                self.logger.error(f"Unexpected error in worker thread {self.thread_id}: {e}")
        
        self.monitor.unregister_thread(self.thread_id)
        self.logger.info(f"Worker thread {self.thread_id} shutting down")
    
    def _execute_task(self, task: Task):
        """Execute a single task with error handling and retries."""
        
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        
        self.logger.debug(f"Executing task {task.id}: {task.name}")
        
        try:
            # Execute with timeout if specified
            if task.timeout:
                import signal
                
                def timeout_handler(signum, frame):
                    raise TimeoutError(f"Task {task.id} timed out after {task.timeout}s")
                
                # Note: signal-based timeout only works on Unix
                if hasattr(signal, 'SIGALRM'):
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(int(task.timeout))
                    
                    try:
                        result = task.function(*task.args, **task.kwargs)
                    finally:
                        signal.alarm(0)
                else:
                    # Fallback for Windows - no timeout
                    result = task.function(*task.args, **task.kwargs)
            else:
                result = task.function(*task.args, **task.kwargs)
            
            # Task completed successfully
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            task.result = result
            
            self.monitor.record_task_completion(self.thread_id, task)
            
            # Call success callback if provided
            if task.callback:
                try:
                    task.callback(result)
                except Exception as e:
                    self.logger.error(f"Error in task callback: {e}")
            
            self.logger.debug(f"Task {task.id} completed successfully")
            
        except Exception as e:
            task.error = e
            task.completed_at = datetime.now()
            
            # Check if should retry
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.status = TaskStatus.PENDING
                
                self.logger.warning(f"Task {task.id} failed, retrying ({task.retry_count}/{task.max_retries}): {e}")
                
                # Re-queue task with same priority
                self.task_queue.put((task.priority.value, task))
            else:
                # Task failed after all retries
                task.status = TaskStatus.FAILED
                
                self.monitor.record_task_failure(self.thread_id, task)
                
                # Call error callback if provided
                if task.error_callback:
                    try:
                        task.error_callback(e)
                    except Exception as cb_error:
                        self.logger.error(f"Error in error callback: {cb_error}")
                
                self.logger.error(f"Task {task.id} failed after {task.retry_count} retries: {e}")


class ManagedQThread(QThread):
    """Managed QThread with lifecycle control and monitoring."""
    
    # Signals
    started_signal = pyqtSignal()
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    
    def __init__(self, target: Callable, args: tuple = (), kwargs: dict = None,
                 name: str = "ManagedThread"):
        super().__init__()
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.name = name
        self.logger = get_logger(__name__)
        self._is_running = False
        self._should_stop = False
        self.result = None
        self.error = None
        
    def run(self):
        """Execute the target function."""
        self._is_running = True
        self.started_signal.emit()
        
        self.logger.info(f"QThread {self.name} started")
        
        try:
            # Pass thread reference to target if it accepts it
            import inspect
            sig = inspect.signature(self.target)
            
            if 'thread' in sig.parameters:
                self.kwargs['thread'] = self
            
            self.result = self.target(*self.args, **self.kwargs)
            
        except Exception as e:
            self.error = e
            self.error_signal.emit(str(e))
            log_exception(self.logger, e, {'thread': self.name})
            
        finally:
            self._is_running = False
            self.finished_signal.emit()
            self.logger.info(f"QThread {self.name} finished")
    
    def stop(self):
        """Request thread to stop."""
        self._should_stop = True
        self.logger.info(f"Stop requested for QThread {self.name}")
    
    def should_stop(self) -> bool:
        """Check if thread should stop."""
        return self._should_stop
    
    def is_running(self) -> bool:
        """Check if thread is running."""
        return self._is_running
    
    def update_progress(self, value: int):
        """Update progress (0-100)."""
        self.progress_signal.emit(value)


class ThreadManager:
    """Central thread management system."""
    
    def __init__(self, max_workers: int = 5):
        self.logger = get_logger(__name__)
        self.max_workers = max_workers
        
        # Task queue and worker threads
        self.task_queue = queue.PriorityQueue()
        self.shutdown_event = threading.Event()
        self.monitor = ThreadMonitor()
        
        # Thread pool executor for simple tasks
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
        # Worker threads
        self.worker_threads: List[WorkerThread] = []
        
        # QThread management
        self.managed_qthreads: Dict[str, ManagedQThread] = {}
        
        # Start worker threads
        self._start_workers()
        
        self.logger.info(f"ThreadManager initialized with {max_workers} workers")
    
    def _start_workers(self):
        """Start worker threads."""
        for i in range(self.max_workers):
            thread_id = f"worker_{i}"
            worker = WorkerThread(self.task_queue, self.monitor, thread_id, self.shutdown_event)
            worker.start()
            self.worker_threads.append(worker)
    
    def submit_task(self, function: Callable, args: tuple = (), kwargs: dict = None,
                   priority: TaskPriority = TaskPriority.NORMAL,
                   callback: Optional[Callable] = None,
                   error_callback: Optional[Callable] = None,
                   timeout: Optional[float] = None,
                   task_name: Optional[str] = None) -> str:
        """Submit a task to the thread pool."""
        
        kwargs = kwargs or {}
        task_id = f"task_{datetime.now().timestamp()}_{id(function)}"
        task_name = task_name or function.__name__
        
        task = Task(
            id=task_id,
            name=task_name,
            function=function,
            args=args,
            kwargs=kwargs,
            priority=priority,
            callback=callback,
            error_callback=error_callback,
            timeout=timeout
        )
        
        self.task_queue.put((priority.value, task))
        
        self.logger.debug(f"Task {task_id} ({task_name}) submitted with priority {priority.name}")
        
        return task_id
    
    def submit_simple_task(self, function: Callable, *args, **kwargs) -> Future:
        """Submit a simple task using ThreadPoolExecutor."""
        return self.executor.submit(function, *args, **kwargs)
    
    def create_managed_qthread(self, target: Callable, args: tuple = (), 
                              kwargs: dict = None, name: str = None) -> ManagedQThread:
        """Create and manage a QThread."""
        
        name = name or f"qthread_{datetime.now().timestamp()}"
        
        thread = ManagedQThread(target, args, kwargs, name)
        self.managed_qthreads[name] = thread
        
        # Auto-cleanup on finish
        thread.finished.connect(lambda: self._cleanup_qthread(name))
        
        return thread
    
    def _cleanup_qthread(self, name: str):
        """Clean up finished QThread."""
        if name in self.managed_qthreads:
            thread = self.managed_qthreads[name]
            if not thread.is_running():
                del self.managed_qthreads[name]
                self.logger.debug(f"Cleaned up QThread {name}")
    
    def stop_all_qthreads(self, timeout: float = 5.0):
        """Stop all managed QThreads."""
        
        for name, thread in list(self.managed_qthreads.items()):
            thread.stop()
            
            if not thread.wait(int(timeout * 1000)):
                self.logger.warning(f"QThread {name} did not stop gracefully, terminating")
                thread.terminate()
                thread.wait()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get thread manager statistics."""
        
        stats = self.monitor.get_statistics()
        stats.update({
            'queue_size': self.task_queue.qsize(),
            'active_qthreads': len([t for t in self.managed_qthreads.values() if t.is_running()]),
            'total_qthreads': len(self.managed_qthreads)
        })
        
        return stats
    
    def shutdown(self, timeout: float = 10.0):
        """Shutdown thread manager gracefully."""
        
        self.logger.info("Shutting down ThreadManager")
        
        # Stop accepting new tasks
        self.shutdown_event.set()
        
        # Wait for queue to empty
        start_time = time.time()
        while not self.task_queue.empty() and time.time() - start_time < timeout:
            time.sleep(0.1)
        
        # Stop QThreads
        self.stop_all_qthreads(timeout / 2)
        
        # Shutdown executor
        self.executor.shutdown(wait=True, timeout=timeout / 2)
        
        # Wait for worker threads
        for worker in self.worker_threads:
            worker.join(timeout / len(self.worker_threads))
            
            if worker.is_alive():
                self.logger.warning(f"Worker thread {worker.thread_id} did not stop gracefully")
        
        self.logger.info("ThreadManager shutdown complete")