import os
import configparser


class ConfigManager:
    """配置管理器 - 单例模式"""
    
    _instance = None
    _config = None
    
    def __new__(cls):
        """确保只有一个配置管理器实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self):
        """加载配置文件"""
        self._config = configparser.ConfigParser()
        
        # 获取配置文件路径（与主程序同目录）
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.ini')
        
        # 如果配置文件不存在，创建默认配置
        if not os.path.exists(config_path):
            self._create_default_config(config_path)
        
        # 读取配置文件
        self._config.read(config_path, encoding='utf-8')
        self.config_path = config_path
    
    def _create_default_config(self, config_path):
        """创建默认配置文件"""
        default_config = configparser.ConfigParser()
        
        # 下载配置
        default_config['download'] = {
            'save_directory': './downloads',
            'max_concurrent_tasks': '3',
            'convert_to_mp4': 'false'
        }
        
        # Cookies 配置
        default_config['cookies'] = {
            'cookies_file': ''
        }
        
        # FFmpeg 配置
        default_config['ffmpeg'] = {
            'ffmpeg_path': ''
        }
        
        # N_m3u8DL-RE 配置
        default_config['n_m3u8dl_re'] = {
            'n_m3u8dl_re_path': ''
        }

        # Webhook 配置
        default_config['webhook'] = {
            'port': '5001'
        }
        
        # 写入配置文件
        with open(config_path, 'w', encoding='utf-8') as f:
            default_config.write(f)
    
    def get(self, section, key, fallback=None):
        """
        获取配置项
        
        Args:
            section: 配置节名称
            key: 配置键名称
            fallback: 默认值
            
        Returns:
            配置值
        """
        try:
            return self._config.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback
    
    def getint(self, section, key, fallback=0):
        """获取整数类型配置项"""
        try:
            return self._config.getint(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return fallback
    
    def set(self, section, key, value):
        """
        设置配置项并立即保存到文件
        
        Args:
            section: 配置节名称
            key: 配置键名称
            value: 配置值
        """
        # 确保节存在
        if not self._config.has_section(section):
            self._config.add_section(section)
        
        # 设置值
        self._config.set(section, key, str(value))
        
        # 立即保存到文件
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self._config.write(f)
    
    def get_save_directory(self):
        """获取下载保存目录"""
        save_dir = self.get('download', 'save_directory', './downloads')
        
        # 如果是相对路径，转换为绝对路径
        if not os.path.isabs(save_dir):
            save_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), save_dir)
        
        # 确保目录存在
        os.makedirs(save_dir, exist_ok=True)
        
        return save_dir
    
    def get_max_concurrent_tasks(self):
        """获取最大并发任务数"""
        return self.getint('download', 'max_concurrent_tasks', 3)
    
    def get_cookies_file(self):
        """获取 cookies 文件路径"""
        return self.get('cookies', 'cookies_file', '')
    
    def get_ffmpeg_path(self):
        """获取 FFmpeg 路径"""
        return self.get('ffmpeg', 'ffmpeg_path', '')
    
    def get_n_m3u8dl_re_path(self):
        """获取 N_m3u8DL-RE 路径"""
        return self.get('n_m3u8dl_re', 'n_m3u8dl_re_path', '')

    def get_webhook_port(self):
        """获取 Webhook 端口"""
        return self.getint('webhook', 'port', 5001)

    def set_webhook_port(self, port: int):
        """设置 Webhook 端口"""
        self.set('webhook', 'port', str(port))

    def get_convert_to_mp4(self):
        """获取是否转换为MP4格式的选项"""
        value = self.get('download', 'convert_to_mp4', 'false')
        return value.lower() in ('true', '1', 'yes', 'on')

    def set_convert_to_mp4(self, enabled: bool):
        """设置是否转换为MP4格式"""
        self.set('download', 'convert_to_mp4', str(enabled).lower())
    
    def reset_to_default(self):
        """重置为默认配置"""
        self._create_default_config(self.config_path)
        self._load_config()
