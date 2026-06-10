"""
任务管理模块
"""
import threading
from typing import List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor

from xlvideo.config import ConfigManager
from xlvideo.logger import LogManager
from xlvideo.engine import DownloadTask, DownloadEngine, DownloadStatus


class TaskManager:
    """任务管理器 - 单例模式"""
    
    _instance = None
    
    def __new__(cls):
        """确保只有一个任务管理器实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """初始化任务管理器"""
        self.config = ConfigManager()
        self.logger = LogManager()
        self.engine = DownloadEngine()
        
        # 任务列表和锁
        self.tasks: List[DownloadTask] = []
        self.tasks_lock = threading.Lock()
        
        # 任务计数器（用于生成唯一的 task_id）
        self.task_counter = 0
        self.counter_lock = threading.Lock()
        
        # 线程池（控制并发数）
        self.executor: Optional[ThreadPoolExecutor] = None
        self.max_workers = self.config.get_max_concurrent_tasks()
        
        # 进度回调函数列表
        self.progress_callbacks: List[Callable] = []
        
        self.logger.info("任务管理器初始化完成")
    
    def _get_next_task_id(self) -> int:
        """获取下一个任务 ID（线程安全）"""
        with self.counter_lock:
            self.task_counter += 1
            return self.task_counter
    
    def add_task(self, url: str, custom_name: str = "") -> DownloadTask:
        """
        添加新的下载任务
        
        Args:
            url: 视频链接
            custom_name: 自定义视频名称
            
        Returns:
            DownloadTask: 新创建的任务对象
        """
        # 生成任务 ID
        task_id = self._get_next_task_id()
        
        # 创建任务
        task = DownloadTask(task_id, url, custom_name)
        
        # 添加到任务列表
        with self.tasks_lock:
            self.tasks.append(task)
        
        self.logger.info(f"添加新任务 {task_id}: {url}")
        
        # 提交到线程池执行
        self._submit_task(task)
        
        return task
    
    def _submit_task(self, task: DownloadTask):
        """
        提交任务到线程池
        
        Args:
            task: 下载任务对象
        """
        # 如果线程池未初始化或已关闭，重新创建
        if self.executor is None or self.executor._shutdown:
            self.max_workers = self.config.get_max_concurrent_tasks()
            self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        
        # 提交任务
        future = self.executor.submit(
            self._execute_task,
            task,
            self._on_progress_update
        )
        
        # 添加回调处理异常
        future.add_done_callback(lambda f: self._on_task_complete(task, f))
    
    def _execute_task(self, task: DownloadTask, progress_callback: Callable):
        """
        执行下载任务
        
        Args:
            task: 下载任务对象
            progress_callback: 进度回调函数
        """
        try:
            self.engine.download(task, progress_callback)
        except Exception as e:
            self.logger.error(f"任务 {task.task_id} 执行异常: {str(e)}")
            task.error_message = str(e)
            task.update_status(DownloadStatus.FAILED)
    
    def _on_progress_update(self, task_id: int, progress: float):
        """
        进度更新回调
        
        Args:
            task_id: 任务 ID
            progress: 进度百分比
        """
        # 通知所有注册的回调函数
        for callback in self.progress_callbacks:
            try:
                callback(task_id, progress)
            except Exception as e:
                self.logger.error(f"进度回调执行失败: {str(e)}")
    
    def _on_task_complete(self, task: DownloadTask, future):
        """
        任务完成回调
        
        Args:
            task: 下载任务对象
            future: Future 对象
        """
        # 检查是否有异常
        try:
            future.result()
        except Exception as e:
            self.logger.error(f"任务 {task.task_id} 完成时发生异常: {str(e)}")
            if task.get_status() == DownloadStatus.DOWNLOADING:
                task.error_message = str(e)
                task.update_status(DownloadStatus.FAILED)
    
    def pause_task(self, task_id: int) -> bool:
        """
        暂停指定任务
        
        Args:
            task_id: 任务 ID
            
        Returns:
            bool: 是否成功暂停
        """
        task = self.get_task(task_id)
        if task and task.get_status() == DownloadStatus.DOWNLOADING:
            self.engine.pause_task(task)
            return True
        return False
    
    def cancel_task(self, task_id: int) -> bool:
        """
        取消指定任务
        
        Args:
            task_id: 任务 ID
            
        Returns:
            bool: 是否成功取消
        """
        task = self.get_task(task_id)
        if task and task.get_status() in [DownloadStatus.DOWNLOADING, DownloadStatus.PENDING, DownloadStatus.PAUSED]:
            self.engine.cancel_task(task)
            return True
        return False
    
    def remove_task(self, task_id: int) -> bool:
        """
        删除任务记录（仅从列表中移除，不删除文件）
        
        Args:
            task_id: 任务 ID
            
        Returns:
            bool: 是否成功删除
        """
        with self.tasks_lock:
            for i, task in enumerate(self.tasks):
                if task.task_id == task_id:
                    # 只能删除已完成、失败或已取消的任务
                    if task.get_status() in [DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED]:
                        self.tasks.pop(i)
                        self.logger.info(f"任务 {task_id} 记录已从列表中删除")
                        return True
                    else:
                        self.logger.warning(f"任务 {task_id} 状态为 {task.get_status().value}，无法删除")
                        return False
        self.logger.warning(f"任务 {task_id} 不存在")
        return False
    
    def get_task(self, task_id: int) -> Optional[DownloadTask]:
        """
        获取指定任务
        
        Args:
            task_id: 任务 ID
            
        Returns:
            DownloadTask: 任务对象，不存在则返回 None
        """
        with self.tasks_lock:
            for task in self.tasks:
                if task.task_id == task_id:
                    return task
        return None
    
    def get_all_tasks(self) -> List[DownloadTask]:
        """
        获取所有任务
        
        Returns:
            List[DownloadTask]: 任务列表
        """
        with self.tasks_lock:
            return list(self.tasks)
    
    def get_tasks_by_status(self, status: DownloadStatus) -> List[DownloadTask]:
        """
        获取指定状态的任务
        
        Args:
            status: 下载状态
            
        Returns:
            List[DownloadTask]: 任务列表
        """
        with self.tasks_lock:
            return [task for task in self.tasks if task.get_status() == status]
    
    def register_progress_callback(self, callback: Callable):
        """
        注册进度回调函数
        
        Args:
            callback: 回调函数，签名为 callback(task_id, progress)
        """
        self.progress_callbacks.append(callback)
        self.logger.info("注册新的进度回调函数")
    
    def update_max_concurrent_tasks(self, max_workers: int):
        """
        更新最大并发任务数
        
        Args:
            max_workers: 最大并发数
        """
        self.max_workers = max_workers
        self.config.set('download', 'max_concurrent_tasks', max_workers)
        
        # 重建线程池
        if self.executor:
            # 不关闭旧的线程池，等待正在执行的任务完成
            # 新任务将使用新的并发数
            old_executor = self.executor
            self.executor = None
            
            # 在新线程中关闭旧的线程池
            def shutdown_executor():
                old_executor.shutdown(wait=True)
            
            threading.Thread(target=shutdown_executor, daemon=True).start()
        
        self.logger.info(f"更新最大并发任务数为: {max_workers}")
    
    def shutdown(self):
        """关闭任务管理器"""
        if self.executor:
            self.executor.shutdown(wait=False)
            self.logger.info("任务管理器已关闭")
