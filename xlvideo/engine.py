import os
import re
import subprocess
import threading
from enum import Enum
from typing import Optional, Callable

from xlvideo.config import ConfigManager
from xlvideo.logger import LogManager


def sanitize_filename(name: str, max_bytes: int = 200) -> str:
    """
    净化文件名，防止路径穿越、模板注入和非法字符。

    - 剥离路径分隔符（/ \\ ..），避免自定义名称写穿保存目录
    - 去除 yt-dlp 模板语法中的 %，避免被当作模板字段展开
    - 清理 Windows 保留字符与控制字符
    - 按 UTF-8 字节数截断（中文一个字符占 3 字节）
    """
    if not name:
        return ""
    # 剥离路径部分与危险片段
    name = name.replace('\\', '/').split('/')[-1]
    name = re.sub(r'(?i)\.\.+', '.', name)
    # 去除模板注入与非法字符
    name = re.sub(r'[%<>:"|?*\x00-\x1f]', '_', name).strip(' .')
    if not name:
        return ""
    # 按字节截断，避免超长文件名导致下载失败
    encoded = name.encode('utf-8', errors='ignore')
    if len(encoded) > max_bytes:
        name = encoded[:max_bytes].decode('utf-8', errors='ignore')
    return name


class DownloadStatus(Enum):
    """下载状态枚举"""
    PENDING = "等待中"
    DOWNLOADING = "下载中"
    PAUSED = "已暂停"
    TRANSCODING = "转码中"
    COMPLETED = "已完成"
    FAILED = "失败"
    CANCELLED = "已取消"


class DownloadType(Enum):
    """下载类型枚举"""
    YT_DLP = "yt-dlp"
    N_M3U8DL_RE = "N_m3u8DL-RE"
    Capture_M3U8 ='Capture_M3U8'


class DownloadTask:
    """下载任务类"""
    
    def __init__(self, task_id: int, url: str, custom_name: str = "", headers: Optional[dict] = None):
        """
        初始化下载任务
        
        Args:
            task_id: 任务 ID
            url: 视频链接
            custom_name: 自定义视频名称
            headers: 附加请求头（如 Referer、User-Agent），webhook 推送场景使用
        """
        self.task_id = task_id
        self.url = url
        self.custom_name = custom_name
        self.headers = headers or {}
        self.status = DownloadStatus.PENDING
        self.progress = 0.0  # 进度百分比 (0-100)
        self.download_type: Optional[DownloadType] = None
        self.video_name = ""
        self.error_message = ""
        self.process: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()
        
        # 日志记录器
        self.logger = LogManager()
        self.config = ConfigManager()
    
    def update_status(self, status: DownloadStatus):
        """更新任务状态（线程安全），状态未变化时跳过冗余日志"""
        with self.lock:
            if self.status == status:
                return
            self.status = status
            self.logger.info(f"任务 {self.task_id} 状态更新为: {status.value}")
    
    def should_resume(self) -> bool:
        """任务是否仍应执行（被取消或无需下载时返回 False）"""
        with self.lock:
            return self.status not in (DownloadStatus.CANCELLED,)
    
    def update_progress(self, progress: float):
        """更新下载进度（线程安全）"""
        with self.lock:
            self.progress = max(0.0, min(100.0, progress))
    
    def get_status(self) -> DownloadStatus:
        """获取任务状态（线程安全）"""
        with self.lock:
            return self.status
    
    def get_progress(self) -> float:
        """获取下载进度（线程安全）"""
        with self.lock:
            return self.progress
    
    def to_dict(self) -> dict:
        """转换为字典（用于 API 响应）"""
        return {
            'task_id': self.task_id,
            'url': self.url,
            'custom_name': self.custom_name,
            'video_name': self.video_name,
            'status': self.status.value,
            'progress': round(self.progress, 2),
            'download_type': self.download_type.value if self.download_type else None,
            'error_message': self.error_message
        }


class DownloadEngine:
    """下载引擎 - 智能选择下载工具"""
    
    def __init__(self):
        """初始化下载引擎"""
        self.config = ConfigManager()
        self.logger = LogManager()
    
    def detect_download_type(self, url: str) -> DownloadType:
        """
        检测视频链接类型，决定使用哪种下载工具
        
        Args:
            url: 视频链接
            
        Returns:
            DownloadType: 下载类型
        """
        url_lower = url.lower()
        # 直链媒体文件（含 m3u8 流）：直接交给对应下载器，避免误走页面抓取
        if re.search(r'\.m3u8([?#].*)?$', url_lower) or re.search(r'\.m3u8[/?#]', url_lower):
            self.logger.info(f"检测到 m3u8 链接，使用 N_m3u8DL-RE: {url}")
            return DownloadType.N_M3U8DL_RE
        if re.search(r'\.(mp4|mkv|flv|avi|mov|webm|ts)([?#].*)?$', url_lower):
            self.logger.info(f"检测到直链媒体文件，使用 yt-dlp: {url}")
            return DownloadType.YT_DLP
        if "youtube.com" in url_lower or "youtu.be" in url_lower or "douyin" in url_lower or "bilibili.com" in url_lower:
            self.logger.info(f"检测到普通视频链接，使用 yt-dlp: {url}")
            return DownloadType.YT_DLP
        # 其他情况使用页面抓取（Playwright 解析 m3u8）
        self.logger.info(f"未识别为直链，使用规则抓取页面链接：{url}")
        return DownloadType.Capture_M3U8
    
    def download(self, task: DownloadTask, progress_callback: Optional[Callable] = None):
        """
        执行下载任务
        
        Args:
            task: 下载任务对象
            progress_callback: 进度回调函数
        """
        try:
            # 入口检查：任务在排队期间可能已被取消，此时不应再启动下载
            if not task.should_resume():
                self.logger.info(f"任务 {task.task_id} 已被取消，跳过下载")
                return

            # 检测下载类型（使用解析后的URL）
            task.download_type = self.detect_download_type(task.url)
            
            # 根据类型选择下载方法
            if task.download_type == DownloadType.YT_DLP:
                self._download_with_yt_dlp(task, progress_callback)
            elif task.download_type == DownloadType.N_M3U8DL_RE:
                self._download_with_n_m3u8dl_re(task, progress_callback)
            elif task.download_type == DownloadType.Capture_M3U8:
                self._download_with_capture_m3u8(task, progress_callback)
            else:
                raise ValueError(f"未知的下载类型: {task.download_type}")
            
        except Exception as e:
            # 任务已被取消时不覆盖状态（避免取消后仍显示为失败）
            if task.get_status() in (DownloadStatus.DOWNLOADING, DownloadStatus.PENDING):
                self.logger.error(f"任务 {task.task_id} 下载失败: {str(e)}")
                task.error_message = str(e)
                task.update_status(DownloadStatus.FAILED)
            else:
                self.logger.warning(f"任务 {task.task_id} 下载过程中被取消，忽略异常: {str(e)}")
    
    def _download_with_yt_dlp(self, task: DownloadTask, progress_callback: Optional[Callable] = None):
        """
        使用 yt-dlp 下载视频
        
        Args:
            task: 下载任务对象
            progress_callback: 进度回调函数
        """
        save_dir = self.config.get_save_directory()
        cookies_file = self.config.get_cookies_file()
        ffmpeg_path = self.config.get_ffmpeg_path()
        
        # 构建 yt-dlp 命令
        cmd = ['yt-dlp']
        
        # 设置输出目录和文件名模板（自定义名称先净化，防止路径穿越/模板注入）
        if task.custom_name:
            safe_name = sanitize_filename(task.custom_name)
            output_template = os.path.join(save_dir, f'{safe_name}.%(ext)s')
        else:
            output_template = os.path.join(save_dir, '%(title)s.%(ext)s')
        
        cmd.extend([
            '--output', output_template,
            '--merge-output-format', 'mp4',  # 合并为 mp4 格式
            '--no-playlist',  # 不下载播放列表
            '--newline',  # 每行输出
        ])
        
        # 添加 cookies（如果配置了）
        if cookies_file and os.path.exists(cookies_file):
            cmd.extend(['--cookies', cookies_file])
        
        # 添加 FFmpeg 路径（如果配置了）
        if ffmpeg_path:
            cmd.extend(['--ffmpeg-location', ffmpeg_path])
        
        # 透传 webhook 抓取到的请求头（防盗链站点必需，如 Referer）
        for key, value in (task.headers or {}).items():
            if value and key.lower() in ('referer', 'user-agent', 'origin', 'cookie'):
                cmd.extend(['--add-header', f'{key}: {value}'])
        
        # 添加视频链接
        cmd.append(task.url)
        
        self.logger.info(f"开始 yt-dlp 下载: {' '.join(cmd)}")
        task.update_status(DownloadStatus.DOWNLOADING)
        
        # 执行下载
        try:
            task.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            # 读取输出并解析进度
            for line in task.process.stdout:
                if not task.should_resume():
                    break
                
                line = line.strip()
                
                # 解析进度信息
                if '[download]' in line and '%' in line:
                    # 尝试提取进度百分比
                    match = re.search(r'(\d+\.?\d*)%', line)
                    if match:
                        progress = float(match.group(1))
                        task.update_progress(progress)
                        
                        # 调用进度回调
                        if progress_callback:
                            progress_callback(task.task_id, progress)
                
                # 提取视频名称
                if '[download] Destination:' in line:
                    filename = line.split('Destination:')[-1].strip()
                    task.video_name = os.path.basename(filename)
                    self.logger.debug(f"yt-dlp 目标文件: {task.video_name}")
                elif line and not line.endswith('%'):
                    # 仅记录非进度行，避免进度刷新刷爆日志
                    self.logger.debug(f"yt-dlp 输出: {line[:300]}")
            
            # 等待进程结束
            return_code = task.process.wait()
            
            if task.get_status() == DownloadStatus.CANCELLED:
                self.logger.info(f"任务 {task.task_id} 已取消")
            elif task.get_status() == DownloadStatus.PAUSED:
                self.logger.info(f"任务 {task.task_id} 已暂停")
            elif return_code == 0:
                task.update_progress(100.0)
                task.update_status(DownloadStatus.COMPLETED)
                self.logger.info(f"任务 {task.task_id} 下载完成")
                # 检查是否需要转换为MP4（转码函数内部会切换 TRANSCODING → COMPLETED）
                if self.config.get_convert_to_mp4():
                    self._convert_to_mp4_if_needed(task, save_dir)
            else:
                task.update_status(DownloadStatus.FAILED)
                task.error_message = f"yt-dlp 退出码: {return_code}"
                self.logger.error(f"任务 {task.task_id} 下载失败，退出码: {return_code}")
        
        except Exception as e:
            self.logger.error(f"yt-dlp 下载异常: {str(e)}")
            task.error_message = str(e)
            task.update_status(DownloadStatus.FAILED)
    
    def _download_with_n_m3u8dl_re(self, task: DownloadTask, progress_callback: Optional[Callable] = None):
        """
        使用 N_m3u8DL-RE 下载视频
        
        Args:
            task: 下载任务对象
            progress_callback: 进度回调函数
        """
        save_dir = self.config.get_save_directory()
        n_m3u8dl_re_path = self.config.get_n_m3u8dl_re_path()
        
        # 使用自定义名称（先净化），如果没有则使用默认名称
        video_name = sanitize_filename(task.custom_name) if task.custom_name else f"video_{task.task_id}"
        
        # 构建 N_m3u8DL-RE 命令
        if n_m3u8dl_re_path and os.path.exists(n_m3u8dl_re_path):
            cmd = [n_m3u8dl_re_path]
        else:
            cmd = ['N_m3u8DL-RE']
        
        cmd.extend([
            task.url,
            '--save-dir', save_dir,
            '--save-name', video_name,
            '--auto-select',  # 自动选择最佳质量
            '--binary-merge',  # 二进制合并
        ])
        
        # 透传 webhook 抓取到的请求头（防盗链站点必需）
        for key, value in (task.headers or {}).items():
            if value and key.lower() in ('referer', 'user-agent', 'origin', 'cookie'):
                cmd.extend(['-H', f'{key}: {value}'])
        
        # 如果配置了转换为MP4，添加 mux 参数直接输出MP4格式
        if self.config.get_convert_to_mp4():
            cmd.extend([
                '--mux-after-done', 'format=mp4',  # 下载完成后混流为MP4
            ])
        
        self.logger.info(f"开始 N_m3u8DL-RE 下载: {' '.join(cmd)}")
        task.update_status(DownloadStatus.DOWNLOADING)
        task.video_name = video_name
        
        # 执行下载
        try:
            task.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            # 读取输出并解析进度
            for line in task.process.stdout:
                if not task.should_resume():
                    break
                
                line = line.strip()
                
                # 解析进度信息
                if '%' in line:
                    match = re.search(r'(\d+\.?\d*)%', line)
                    if match:
                        progress = float(match.group(1))
                        task.update_progress(progress)
                        
                        # 调用进度回调
                        if progress_callback:
                            progress_callback(task.task_id, progress)
                elif line:
                    # 仅记录非进度行，避免进度刷新刷爆日志
                    self.logger.debug(f"N_m3u8DL-RE 输出: {line[:300]}")
            
            # 等待进程结束
            return_code = task.process.wait()
            
            if task.get_status() == DownloadStatus.CANCELLED:
                self.logger.info(f"任务 {task.task_id} 已取消")
            elif task.get_status() == DownloadStatus.PAUSED:
                self.logger.info(f"任务 {task.task_id} 已暂停")
            elif return_code == 0:
                task.update_progress(100.0)

                # 检查是否需要转换为MP4
                if self.config.get_convert_to_mp4():
                    # 需要转码，先设置为转码中状态
                    task.update_status(DownloadStatus.TRANSCODING)
                    self._convert_to_mp4_if_needed(task, save_dir)
                else:
                    # 不需要转码，直接设置为已完成
                    task.update_status(DownloadStatus.COMPLETED)
                    self.logger.info(f"任务 {task.task_id} 下载完成")
            else:
                task.update_status(DownloadStatus.FAILED)
                task.error_message = f"N_m3u8DL-RE 退出码: {return_code}"
                self.logger.error(f"任务 {task.task_id} 下载失败，退出码: {return_code}")
        
        except Exception as e:
            self.logger.error(f"N_m3u8DL-RE 下载异常: {str(e)}")
            task.error_message = str(e)
            task.update_status(DownloadStatus.FAILED)

    def _download_with_capture_m3u8(self, task: DownloadTask, progress_callback: Optional[Callable] = None):
        """
        通过捕获页面 m3u8 链接后下载视频
        
        Args:
            task: 下载任务对象
            progress_callback: 进度回调函数
        """
        import asyncio
        from xlvideo.m3u8_tool import M3U8Parser
        
        try:
            self.logger.info(f"开始解析页面获取 m3u8 链接: {task.url}")
            task.update_status(DownloadStatus.DOWNLOADING)
            
            # 创建 M3U8Parser 实例
            parser = M3U8Parser()
            
            # 使用 asyncio 运行异步解析方法
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                results = loop.run_until_complete(parser.parse_m3u8_links(task.url))
            finally:
                loop.close()
            
            if not results:
                raise Exception("未能从页面中解析到 m3u8 链接")
            
            # 解析结果已按优先级排序（master playlist 优先、分片数多的优先），取第一条
            m3u8_url, video_title = results[0]
            
            self.logger.info(f"成功解析到 m3u8 链接: {m3u8_url}")
            self.logger.info(f"视频标题: {video_title}")
            
            # 解析期间任务可能已被取消
            if not task.should_resume():
                self.logger.info(f"任务 {task.task_id} 已取消，放弃下载")
                return
            
            # 如果没有自定义名称，使用解析到的标题（净化，防止非法字符）
            if not task.custom_name and video_title and video_title != "未知标题":
                task.custom_name = sanitize_filename(video_title)
                task.video_name = task.custom_name
            
            # 更新任务的 URL 为 m3u8 链接
            original_url = task.url
            task.url = m3u8_url
            
            # 调用 N_m3u8DL-RE 进行下载
            self.logger.info(f"使用 N_m3u8DL-RE 下载 m3u8 流")
            self._download_with_n_m3u8dl_re(task, progress_callback)
            
        except Exception as e:
            self.logger.error(f"捕获 m3u8 下载失败: {str(e)}")
            if task.get_status() == DownloadStatus.DOWNLOADING:
                task.error_message = f"解析 m3u8 失败: {str(e)}"
                task.update_status(DownloadStatus.FAILED)

    def _convert_to_mp4_if_needed(self, task: DownloadTask, save_dir: str):
        """
        如果视频不是MP4格式，则转换为MP4
        Args:
            task: 下载任务对象
            save_dir: 保存目录
        """
        try:
            import glob
            # 仅按本任务的实际文件名查找（不扫描目录，避免误处理其他任务/无关文件）
            task.update_status(DownloadStatus.TRANSCODING)
            pattern = os.path.join(save_dir, f"{task.video_name}.*")
            files = glob.glob(pattern)

            if not files:
                self.logger.warning(
                    f"任务 {task.task_id}: 未找到预期文件 {task.video_name}，"
                    f"跳过转码（保留原始文件，不做目录级兜底）"
                )
                task.update_status(DownloadStatus.COMPLETED)
                return

            # 获取最新的文件
            video_file = max(files, key=os.path.getmtime)
            file_ext = os.path.splitext(video_file)[1].lower()
            
            # 如果已经是MP4格式，不需要转换
            if file_ext == '.mp4':
                self.logger.info(f"任务 {task.task_id}: 文件已是MP4格式，无需转换")
                task.update_status(DownloadStatus.COMPLETED)
                return
                
            # 检查FFmpeg是否可用
            ffmpeg_path = self.config.get_ffmpeg_path()
            if not ffmpeg_path or not os.path.exists(ffmpeg_path):
                # 尝试使用系统PATH中的ffmpeg
                ffmpeg_path = 'ffmpeg'
                
            # 构建输出文件路径（先转码到临时文件，成功后再替换，避免转换失败破坏原文件）
            output_file = os.path.splitext(video_file)[0] + '.mp4'
            temp_output = output_file + '.tmp'
            self.logger.info(f"任务 {task.task_id}: 开始将 {file_ext} 转换为 MP4...")
            self.logger.info(f"源文件: {video_file}")
            self.logger.info(f"目标文件: {output_file}")

            # 构建FFmpeg命令
            cmd = [
                ffmpeg_path,
                '-i', video_file,
                '-c', 'copy',
                '-movflags', '+faststart',
                '-y',
                temp_output
            ]

            # 执行转换
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )

            if result.returncode == 0 and os.path.exists(temp_output):
                # 转码成功：临时文件转正，再删除原文件
                os.replace(temp_output, output_file)
                self.logger.info(f"任务 {task.task_id}: 成功转换为MP4: {output_file}")
                try:
                    os.remove(video_file)
                    self.logger.info(f"任务 {task.task_id}: 已删除原文件 {video_file}")
                except Exception as e:
                    self.logger.warning(f"任务 {task.task_id}: 删除原文件失败: {str(e)}")

                # 转码完成，更新为已完成状态
                task.update_status(DownloadStatus.COMPLETED)
                self.logger.info(f"任务 {task.task_id} 转码完成")
            else:
                self.logger.error(f"任务 {task.task_id}: 转换失败，返回码: {result.returncode}")
                self.logger.error(f"FFmpeg 输出: {result.stdout}")
                # 清理残留的临时文件
                try:
                    if os.path.exists(temp_output):
                        os.remove(temp_output)
                except OSError:
                    pass
                # 转码失败，也标记为已完成（因为原始文件还在）
                task.update_status(DownloadStatus.COMPLETED)
                self.logger.warning(f"任务 {task.task_id}: 转码失败，但保留原始文件")

        except Exception as e:
            self.logger.error(f"任务 {task.task_id}: 转换MP4时出错: {str(e)}")
            # 转码异常，也标记为已完成（因为原始文件还在）
            task.update_status(DownloadStatus.COMPLETED)
            self.logger.warning(f"任务 {task.task_id}: 转码异常，但保留原始文件")

    def pause_task(self, task: DownloadTask):
        """
        暂停下载任务（终止进程；当前为停止语义，无续传能力）
        
        Args:
            task: 下载任务对象
        """
        if task.process and task.process.poll() is None:
            try:
                task.process.terminate()
                task.update_status(DownloadStatus.PAUSED)
                self.logger.info(f"任务 {task.task_id} 已暂停")
            except Exception as e:
                self.logger.error(f"暂停任务 {task.task_id} 失败: {str(e)}")
    
    def cancel_task(self, task: DownloadTask):
        """
        取消下载任务：下载中终止进程；排队/暂停中直接标记取消。
        无论进程是否存在都会置为 CANCELLED，配合 download() 入口检查，
        保证排队中的任务被取消后不会再启动。
        
        Args:
            task: 下载任务对象
        """
        if task.process and task.process.poll() is None:
            try:
                task.process.terminate()
            except Exception as e:
                self.logger.error(f"终止任务 {task.task_id} 进程失败: {str(e)}")
        task.update_status(DownloadStatus.CANCELLED)
        self.logger.info(f"任务 {task.task_id} 已取消")
