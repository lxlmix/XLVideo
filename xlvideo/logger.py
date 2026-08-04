"""
日志管理模块
提供统一的日志记录功能
"""

import os
import logging
import threading
from logging.handlers import RotatingFileHandler


class LogManager:
    """日志管理器 - 单例模式（线程安全）"""
    
    _instance = None
    _instance_lock = threading.Lock()
    _logger = None
    
    def __new__(cls):
        """确保只有一个日志管理器实例（线程安全）"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._setup_logger()
        return cls._instance
    
    def _setup_logger(self):
        """配置日志记录器"""
        self._logger = logging.getLogger('XLVideo')
        self._logger.setLevel(logging.DEBUG)
        
        # 避免重复添加 handler
        if self._logger.handlers:
            return
        
        # 创建日志目录
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        
        # 日志文件路径
        self.log_file = os.path.join(log_dir, 'xlvideo.log')
        
        # 文件处理器 - 轮转日志（最大 10MB，保留 2 个备份）
        file_handler = RotatingFileHandler(
            self.log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=2,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # 日志格式
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_format = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        
        file_handler.setFormatter(file_format)
        console_handler.setFormatter(console_format)
        
        # 添加处理器
        self._logger.addHandler(file_handler)
        self._logger.addHandler(console_handler)
    
    def get_logger(self):
        """获取日志记录器实例"""
        return self._logger
    
    def debug(self, message):
        """记录调试日志"""
        self._logger.debug(message)
    
    def info(self, message):
        """记录信息日志"""
        self._logger.info(message)
    
    def warning(self, message):
        """记录警告日志"""
        self._logger.warning(message)
    
    def error(self, message):
        """记录错误日志"""
        self._logger.error(message)
    
    def critical(self, message):
        """记录严重错误日志"""
        self._logger.critical(message)
