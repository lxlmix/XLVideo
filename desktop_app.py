import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog,
    QTabWidget, QTextEdit, QSpinBox, QGroupBox, QFormLayout, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont
import json
from datetime import datetime
from threading import Thread

from xlvideo.config import ConfigManager
from xlvideo.logger import LogManager
from xlvideo.task_manager import TaskManager
from xlvideo.engine import DownloadStatus

class WebhookSignalEmitter(QObject):
    """用于在线程间发送信号的辅助类"""
    task_received = pyqtSignal(str, str, dict)  # title, url, metadata


class WebhookServer:
    """Webhook 服务器 - 接收浏览器插件推送"""

    def __init__(self, task_manager, logger, signal_emitter, port=5001):
        self.task_manager = task_manager
        self.logger = logger
        self.signal_emitter = signal_emitter
        self.port = port
        self.app = None
        self.thread = None
        self.running = False

    def start(self):
        """启动 webhook 服务器"""
        try:
            from flask import Flask, request, jsonify

            app = Flask(__name__)

            DATA_DIR = os.getenv('DATA_DIR', './downloads')
            os.makedirs(DATA_DIR, exist_ok=True)

            def save_to_txt(record: dict):
                """保存接收到的数据到文本文件（用于调试）"""
                filename = os.path.join(DATA_DIR, "received_data.txt")
                with open(filename, 'a', encoding='utf-8') as f:
                    f.write("=" * 50 + "\n")
                    f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"Tab ID: {record.get('tabId', '未知')}\n")
                    f.write(f"动作: {record.get('action', '未知')}\n")
                    f.write("数据:\n")
                    data_content = record.get('data')
                    if isinstance(data_content, dict):
                        f.write(json.dumps(data_content, ensure_ascii=False, indent=2))
                    else:
                        f.write(str(data_content))
                    f.write("\n" + "=" * 50 + "\n\n")

            def process_webhook_data(data):
                """处理 webhook 数据"""
                action = data.get('action')
                payload = data.get('data')
                tab_id = data.get('tabId')

                if action not in ('catch', 'addKey'):
                    return jsonify({"error": f"Unsupported action: {action}"}), 400

                self.logger.info(f"Received {action} from tab {tab_id}")
                save_to_txt(data)

                if action == 'catch':
                    if not isinstance(payload, dict):
                        return jsonify({"error": "Expected data to be an object for action 'catch'"}), 400

                    title = payload.get('title', '')
                    url = payload.get('url', '')
                    name = payload.get('name')
                    size = payload.get('size')
                    headers = payload.get('requestHeaders', {})

                    self.logger.info(f"Captured file: name={name}, url={url}, size={size}, referer={headers.get('referer')}")

                    if url:
                        metadata = {
                            'headers': headers,
                            'referer': headers.get('referer', ''),
                            'captured_name': name,
                            'captured_size': size
                        }

                        # 通过信号发送到主线程处理
                        self.signal_emitter.task_received.emit(title if title else '', url, metadata)

                        return jsonify({
                            "status": "ok",
                            "message": "Catch data received and download task queued"
                        }), 200
                    else:
                        return jsonify({"status": "ok", "message": "Catch data received (no URL)"}), 200

                elif action == 'addKey':
                    if not isinstance(payload, str):
                        return jsonify({"error": "Expected data to be a base64 string for action 'addKey'"}), 400
                    self.logger.info(f"Received key (base64 length {len(payload)})")
                    return jsonify({"status": "ok", "message": "Key data received"}), 200

                return jsonify({"error": "Internal error"}), 500

            @app.route('/', methods=['POST'])
            def webhook_root():
                if not request.is_json:
                    return jsonify({"error": "Content-Type must be application/json"}), 415
                data = request.get_json()
                if not data:
                    return jsonify({"error": "Invalid JSON body"}), 400
                return process_webhook_data(data)

            @app.route('/webhook', methods=['POST'])
            def webhook():
                if not request.is_json:
                    return jsonify({"error": "Content-Type must be application/json"}), 415
                data = request.get_json()
                if not data:
                    return jsonify({"error": "Invalid JSON body"}), 400
                return process_webhook_data(data)

            @app.route('/health', methods=['GET'])
            def health_check():
                return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()}), 200

            self.app = app
            self.running = True

            # 在单独的线程中运行 Flask
            def run_flask():
                try:
                    app.run(host='127.0.0.1', port=self.port, debug=False, use_reloader=False)
                except OSError as e:
                    if 'Address already in use' in str(e) or 'errno 10048' in str(e).lower():
                        self.logger.error(f"端口 {self.port} 已被占用，请更换端口")
                    else:
                        self.logger.error(f"Webhook 服务器启动失败: {str(e)}")
                    self.running = False
                except Exception as e:
                    self.logger.error(f"Webhook 服务器启动失败: {str(e)}")
                    self.running = False

            self.thread = Thread(target=run_flask, daemon=True)
            self.thread.start()

            self.logger.info(f"Webhook 服务器已启动，监听端口: {self.port}")
            return True

        except ImportError:
            self.logger.error("缺少 Flask 依赖，无法启动 Webhook 服务器")
            return False
        except Exception as e:
            self.logger.error(f"启动 Webhook 服务器失败: {str(e)}")
            return False

    def stop(self):
        """停止 webhook 服务器（daemon 线程，进程退出即终止；
        Flask 的 werkzeug 无法在独立线程中优雅关闭，此处仅置标志位）"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        self.logger.info("Webhook 服务器已停止（随进程退出）")

class MainWindow(QMainWindow):
    """主窗口类"""
    
    def __init__(self):
        super().__init__()
        
        # 初始化管理器
        self.config = ConfigManager()
        self.logger = LogManager()
        self.task_manager = TaskManager()

        # 创建信号发射器
        self.signal_emitter = WebhookSignalEmitter()
        self.signal_emitter.task_received.connect(self.on_webhook_task_received)
        
        # 注册进度回调
        self.task_manager.register_progress_callback(self.on_progress_update)
        
        # 初始化界面
        self.init_ui()
        
        # 启动定时刷新
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_task_list)
        self.refresh_timer.start(1000)  # 每秒刷新一次

        # 启动 Webhook 服务器
        webhook_port = self.config.get_webhook_port()
        self.webhook_server = WebhookServer(self.task_manager, self.logger, self.signal_emitter, port=webhook_port)
        self.webhook_server.start()
        
        self.logger.info("桌面端应用启动")

    def on_webhook_task_received(self, title: str, url: str, metadata: dict):
        """在主线程中处理 Webhook 接收到的任务"""
        try:
            # 把插件抓到的请求头（Referer/UA 等）透传给下载器，防盗链站点必需
            headers = {}
            captured_headers = metadata.get('headers') or {}
            if isinstance(captured_headers, dict):
                for key in ('Referer', 'User-Agent', 'Origin', 'Cookie'):
                    value = captured_headers.get(key)
                    if value:
                        headers[key] = value
            task = self.task_manager.add_task(url, title, headers)
            self.logger.info(f"✓ 下载任务已添加 - Task ID: {task.task_id}, Title: {title}")
            self.refresh_task_list()
        except Exception as e:
            self.logger.error(f"✗ 添加下载任务失败: {str(e)}")
    
    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle('XLVideo - 视频下载器')
        self.setGeometry(500, 200, 800, 600)
        
        # 设置现代白色渐变风格
        self.set_mac_style()
        
        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局 - 减小边距和间距
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)
        
        # 创建标签页
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet(self.get_tab_style())
        
        # 主页标签
        home_tab = self.create_home_tab()
        tab_widget.addTab(home_tab, "主页")
        
        # 设置标签
        settings_tab = self.create_settings_tab()
        tab_widget.addTab(settings_tab, "设置")
        
        main_layout.addWidget(tab_widget)
    
    def set_mac_style(self):
        """设置现代白色渐变风格样式"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #ffffff,
                    stop: 1 #f8f9fa
                );
            }
            QWidget {
                background-color: #ffffff;
                color: #2c3e50;
            }
            QLabel {
                color: #2c3e50;
                font-size: 14px;
                font-weight: 500;
            }
            QLineEdit {
                padding: 12px 16px;
                border: 2px solid #e9ecef;
                border-radius: 12px;
                background-color: #ffffff;
                font-size: 14px;
                selection-background-color: #667eea;
                selection-color: white;
            }
            QLineEdit:focus {
                border: 2px solid #667eea;
                background-color: #fafbff;
            }
            QLineEdit:hover {
                border: 2px solid #dee2e6;
            }
            QPushButton {
                padding: 12px 24px;
                border: none;
                border-radius: 12px;
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #667eea,
                    stop: 1 #764ba2
                );
                color: white;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #764ba2,
                    stop: 1 #667eea
                );
            }
            QPushButton:pressed {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #5568d3,
                    stop: 1 #6a3f91
                );
            }
            QPushButton#secondary {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #e6f4ff,
                    stop: 1 #b3d8ff
                );
                color: #495057;
                border: 1px solid #dee2e6;
            }
            QPushButton#secondary:hover {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #e6f4ff,
                    stop: 1 #b3d8ff
                );
            }
            QPushButton#danger {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #e6f4ff,
                    stop: 1 #b3d8ff
                );
                color: white;
                border: 1px solid #dee2e6;
            }
            QPushButton#danger:hover {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #e6f4ff,
                    stop: 1 #b3d8ff
                );
            }
            QPushButton#success {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #51cf66,
                    stop: 1 #40c057
                );
                color: white;
            }
            QPushButton#success:hover {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #40c057,
                    stop: 1 #51cf66
                );
            }
            QTableWidget {
                border: 2px solid #e9ecef;
                border-radius: 16px;
                background-color: #ffffff;
                gridline-color: #f1f3f5;
                selection-background-color: #e7f5ff;
                alternate-background-color: #f8f9fa;
            }
            QTableWidget::item {
                padding: 12px 8px;
                border-bottom: 1px solid #f1f3f5;
            }
            QTableWidget::item:selected {
                background-color: #e7f5ff;
                color: #2c3e50;
            }
            QHeaderView::section {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #f8f9fa,
                    stop: 1 #f1f3f5
                );
                padding: 14px 10px;
                border: none;
                border-bottom: 2px solid #e9ecef;
                border-right: 1px solid #f1f3f5;
                font-weight: 600;
                color: #495057;
                font-size: 13px;
            }
            QHeaderView::section:first {
                border-top-left-radius: 14px;
            }
            QHeaderView::section:last {
                border-top-right-radius: 14px;
            }
            QProgressBar {
                border: none;
                border-radius: 10px;
                background-color: #e9ecef;
                text-align: center;
                height: 24px;
                font-size: 12px;
                font-weight: 600;
                color: #495057;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #667eea,
                    stop: 1 #764ba2
                );
                border-radius: 10px;
            }
            QTabWidget::pane {
                border: 2px solid #e9ecef;
                border-radius: 16px;
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #ffffff,
                    stop: 1 #fafbfc
                );
            }
            QTabBar::tab {
                padding: 14px 28px;
                border: 2px solid transparent;
                border-bottom: none;
                border-top-left-radius: 14px;
                border-top-right-radius: 14px;
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #f8f9fa,
                    stop: 1 #e9ecef
                );
                color: #6c757d;
                font-weight: 600;
                font-size: 14px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #ffffff,
                    stop: 1 #f8f9fa
                );
                border: 2px solid #e9ecef;
                border-bottom: 2px solid #ffffff;
                color: #667eea;
            }
            QTabBar::tab:hover:!selected {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #e9ecef,
                    stop: 1 #dee2e6
                );
                color: #495057;
            }
            QGroupBox {
                border: 2px solid #e9ecef;
                border-radius: 16px;
                margin-top: 16px;
                padding-top: 20px;
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #ffffff,
                    stop: 1 #fafbfc
                );
                font-weight: 600;
                font-size: 15px;
                color: #495057;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 20px;
                padding: 0 10px;
                background-color: transparent;
                color: #667eea;
            }
            QSpinBox {
                padding: 10px 12px;
                border: 2px solid #e9ecef;
                border-radius: 10px;
                background-color: #ffffff;
                font-size: 14px;
                min-width: 80px;
            }
            QSpinBox:focus {
                border: 2px solid #667eea;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                border: none;
                background-color: transparent;
                width: 20px;
            }
            QTextEdit {
                border: 2px solid #e9ecef;
                border-radius: 12px;
                background-color: #ffffff;
                padding: 12px;
                font-size: 13px;
            }
            QTextEdit:focus {
                border: 2px solid #667eea;
            }
            QScrollBar:vertical {
                border: none;
                background-color: #f8f9fa;
                width: 12px;
                border-radius: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #667eea,
                    stop: 1 #764ba2
                );
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #764ba2,
                    stop: 1 #667eea
                );
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                border: none;
                background-color: #f8f9fa;
                height: 12px;
                border-radius: 6px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #667eea,
                    stop: 1 #764ba2
                );
                border-radius: 6px;
                min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #764ba2,
                    stop: 1 #667eea
                );
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
        """)
    
    def get_tab_style(self):
        """获取标签页样式"""
        return """
            QTabWidget::pane {
                border: none;
                background-color: transparent;
            }
        """
    
    def create_home_tab(self) -> QWidget:
        """创建主页标签"""
        home_widget = QWidget()
        layout = QVBoxLayout(home_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # 输入区域
        input_group = QGroupBox("添加下载任务")
        input_layout = QFormLayout(input_group)
        input_layout.setSpacing(12)
        input_layout.setContentsMargins(16, 20, 16, 16)
        input_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        
        # 设置标签样式
        input_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        # 视频链接输入
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("请输入视频链接...")
        self.url_input.setMinimumHeight(44)
        input_layout.addRow("视频链接:", self.url_input)
        
        # 自定义名称输入
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("可选，留空则自动识别")
        self.name_input.setMinimumHeight(44)
        input_layout.addRow("视频名称:", self.name_input)
        
        # 提交按钮和清空按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        submit_btn = QPushButton("添加任务")
        submit_btn.setMinimumHeight(44)
        submit_btn.clicked.connect(self.add_download_task)

        clear_completed_btn = QPushButton("清空已完成")
        clear_completed_btn.setObjectName("secondary")
        clear_completed_btn.setMinimumHeight(44)
        clear_completed_btn.clicked.connect(self.clear_completed_tasks)

        btn_layout.addWidget(submit_btn)
        btn_layout.addWidget(clear_completed_btn)
        btn_layout.addStretch()
        input_layout.addRow("", btn_layout)
        
        layout.addWidget(input_group)
        
        # 任务列表
        list_group = QGroupBox("下载列表")
        list_layout = QVBoxLayout(list_group)
        list_layout.setContentsMargins(12, 16, 12, 12)
        
        self.task_table = QTableWidget()
        self.task_table.setColumnCount(7)
        self.task_table.setHorizontalHeaderLabels([
            "序号", "视频名称", "链接", "进度", "状态", "类型", "操作"
        ])
        # 设置列宽调整模式：混合模式，部分列自适应拉伸
        header = self.task_table.horizontalHeader()
        # 关键列固定宽度，其他列自适应
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)      # 序号 - 固定
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)   # 视频名称 - 拉伸
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)   # 链接 - 拉伸
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)     # 进度 - 固定
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)     # 状态 - 固定
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)     # 类型 - 固定
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)     # 操作 - 固定
        header.setMinimumSectionSize(60)
        
        # 设置固定列的宽度
        self.task_table.setColumnWidth(0, 50)   # 序号
        self.task_table.setColumnWidth(3, 150)  # 进度
        self.task_table.setColumnWidth(4, 90)   # 状态
        self.task_table.setColumnWidth(5, 90)   # 类型
        self.task_table.setColumnWidth(6, 120)  # 操作
        
        # 启用横向滚动条（仅在需要时显示）
        self.task_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.task_table.setAlternatingRowColors(True)
        
        # 设置行高 - 可以根据需要调整这个值
        self.task_table.verticalHeader().setDefaultSectionSize(50)  # 默认行高 50px
        # 如果需要更紧凑的布局，可以设置为 40-45
        # 如果需要更宽松的布局，可以设置为 55-60
        
        list_layout.addWidget(self.task_table)
        layout.addWidget(list_group)
        
        return home_widget
    
    def create_settings_tab(self) -> QWidget:
        """创建设置标签"""
        settings_widget = QWidget()
        layout = QVBoxLayout(settings_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # 下载设置
        download_group = QGroupBox("下载设置")
        download_layout = QFormLayout(download_group)
        download_layout.setSpacing(12)
        download_layout.setContentsMargins(16, 20, 16, 16)
        download_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        download_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        # 保存目录
        dir_layout = QHBoxLayout()
        dir_layout.setSpacing(10)
        self.save_dir_input = QLineEdit()
        self.save_dir_input.setText(self.config.get_save_directory())
        self.save_dir_input.setReadOnly(True)
        self.save_dir_input.setMinimumHeight(44)
        browse_btn = QPushButton("浏览")
        browse_btn.setObjectName("secondary")
        browse_btn.setFixedWidth(80)
        browse_btn.setMinimumHeight(44)
        browse_btn.clicked.connect(self.browse_save_directory)
        dir_layout.addWidget(self.save_dir_input)
        dir_layout.addWidget(browse_btn)
        download_layout.addRow("保存目录:", dir_layout)
        
        # 最大并发数
        self.max_concurrent_spin = QSpinBox()
        self.max_concurrent_spin.setMinimum(1)
        self.max_concurrent_spin.setMaximum(10)
        self.max_concurrent_spin.setValue(self.config.get_max_concurrent_tasks())
        self.max_concurrent_spin.setMinimumHeight(44)
        download_layout.addRow("最大并发数:", self.max_concurrent_spin)

        # 转换为MP4选项
        self.convert_to_mp4_checkbox = QCheckBox("下载完成后自动将非MP4格式视频转换为MP4")
        self.convert_to_mp4_checkbox.setChecked(self.config.get_convert_to_mp4())
        self.convert_to_mp4_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 14px;
                color: #2c3e50;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                border: 2px solid #e9ecef;
                border-radius: 6px;
                background-color: white;
            }
            QCheckBox::indicator:checked {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #667eea,
                    stop: 1 #764ba2
                );
                border: 2px solid #667eea;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #667eea;
            }
        """)
        download_layout.addRow("", self.convert_to_mp4_checkbox)

        layout.addWidget(download_group)

        # Webhook 设置
        webhook_group = QGroupBox("推送接收设置")
        webhook_layout = QFormLayout(webhook_group)
        webhook_layout.setSpacing(12)
        webhook_layout.setContentsMargins(16, 20, 16, 16)
        webhook_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        webhook_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Webhook 端口设置
        self.webhook_port_spin = QSpinBox()
        self.webhook_port_spin.setMinimum(1024)
        self.webhook_port_spin.setMaximum(65535)
        self.webhook_port_spin.setValue(self.config.get_webhook_port())
        self.webhook_port_spin.setMinimumHeight(44)
        webhook_layout.addRow("Webhook 端口:", self.webhook_port_spin)

        # Webhook 状态信息
        webhook_info_layout = QVBoxLayout()
        webhook_info_layout.setSpacing(8)

        webhook_status_label = QLabel("✓ Webhook 服务器正在运行")
        webhook_status_label.setStyleSheet("""
            QLabel {
                color: #34c759;
                font-weight: 600;
                font-size: 13px;
            }
        """)
        webhook_info_layout.addWidget(webhook_status_label)

        webhook_desc_label = QLabel(f"浏览器插件可以推送到: http://localhost:{self.config.get_webhook_port()}/webhook")
        webhook_desc_label.setStyleSheet("""
            QLabel {
                color: #6c757d;
                font-size: 12px;
            }
        """)
        webhook_desc_label.setWordWrap(True)
        webhook_info_layout.addWidget(webhook_desc_label)

        webhook_layout.addRow("状态:", webhook_info_layout)

        layout.addWidget(webhook_group)
        
        # Cookies 设置
        cookies_group = QGroupBox("Cookies 设置（可选）")
        cookies_layout = QFormLayout(cookies_group)
        cookies_layout.setSpacing(12)
        cookies_layout.setContentsMargins(16, 20, 16, 16)
        cookies_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        cookies_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        cookies_dir_layout = QHBoxLayout()
        cookies_dir_layout.setSpacing(10)
        self.cookies_input = QLineEdit()
        self.cookies_input.setText(self.config.get_cookies_file())
        self.cookies_input.setPlaceholderText("选择 cookies.txt 文件...")
        self.cookies_input.setMinimumHeight(44)
        cookies_browse_btn = QPushButton("浏览")
        cookies_browse_btn.setObjectName("secondary")
        cookies_browse_btn.setFixedWidth(80)
        cookies_browse_btn.setMinimumHeight(44)
        cookies_browse_btn.clicked.connect(self.browse_cookies_file)
        cookies_dir_layout.addWidget(self.cookies_input)
        cookies_dir_layout.addWidget(cookies_browse_btn)
        cookies_layout.addRow("Cookies 文件:", cookies_dir_layout)
        
        layout.addWidget(cookies_group)
        
        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        reset_btn = QPushButton("重置为默认")
        reset_btn.setObjectName("secondary")
        reset_btn.setMinimumHeight(44)
        reset_btn.clicked.connect(self.reset_settings)
        
        save_btn = QPushButton("保存设置")
        save_btn.setObjectName("success")
        save_btn.setMinimumHeight(44)
        save_btn.clicked.connect(self.save_settings)
        
        btn_layout.addStretch()
        btn_layout.addWidget(reset_btn)
        btn_layout.addWidget(save_btn)
        
        layout.addLayout(btn_layout)
        layout.addStretch()
        
        return settings_widget
    
    def add_download_task(self):
        """添加下载任务"""
        url = self.url_input.text().strip()
        custom_name = self.name_input.text().strip()
        
        if not url:
            QMessageBox.warning(self, "警告", "请输入视频链接！")
            return
        
        # 添加任务
        try:
            task = self.task_manager.add_task(url, custom_name)
            self.logger.info(f"成功添加任务: {task.task_id}")
            
            # 清空输入框
            self.url_input.clear()
            self.name_input.clear()
            
            # 刷新任务列表
            self.refresh_task_list()
            
            QMessageBox.information(self, "成功", f"任务 {task.task_id} 已添加！")
        except Exception as e:
            self.logger.error(f"添加任务失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"添加任务失败: {str(e)}")
    
    def refresh_task_list(self):
        """增量刷新任务列表：行数变化时才增删行，其余只更新数据，
        避免每秒重建全部控件导致界面闪烁、选中丢失、按钮点空"""
        tasks = self.task_manager.get_all_tasks()
        
        # 记录每行对应的 task_id，用于识别状态变化是否需要重建操作按钮
        if not hasattr(self, '_row_task_ids'):
            self._row_task_ids = {}
        
        row_count = self.task_table.rowCount()
        if len(tasks) != row_count:
            # 行数变化（增删任务）才整体重置
            self.task_table.setRowCount(len(tasks))
            self._row_task_ids = {}
        
        for row, task in enumerate(tasks):
            task_id = task.task_id
            previous_id = self._row_task_ids.get(row)
            if previous_id != task_id:
                # 该行是新增/换位，清空该行残留控件
                self.task_table.removeCellWidget(row, 3)
                self.task_table.removeCellWidget(row, 6)
                self._row_task_ids[row] = task_id
            
            # 序号
            item = self.task_table.item(row, 0)
            if item is None or item.text() != str(task_id):
                self.task_table.setItem(row, 0, QTableWidgetItem(str(task_id)))
            
            # 视频名称
            video_name = task.video_name if task.video_name else task.custom_name if task.custom_name else "-"
            item = self.task_table.item(row, 1)
            if item is None or item.text() != video_name:
                self.task_table.setItem(row, 1, QTableWidgetItem(video_name))
            
            # 链接（截断显示）
            url_display = task.url[:50] + "..." if len(task.url) > 50 else task.url
            item = self.task_table.item(row, 2)
            if item is None or item.text() != url_display:
                self.task_table.setItem(row, 2, QTableWidgetItem(url_display))
            
            # 进度条（复用已有控件，仅更新数值）
            progress_bar = self.task_table.cellWidget(row, 3)
            if progress_bar is None:
                progress_bar = QProgressBar()
                progress_bar.setTextVisible(True)
                self.task_table.setCellWidget(row, 3, progress_bar)
            if int(progress_bar.value()) != int(task.get_progress()):
                progress_bar.setValue(int(task.get_progress()))
            
            # 状态
            status_text = task.get_status().value
            item = self.task_table.item(row, 4)
            if item is None or item.text() != status_text:
                self.task_table.setItem(row, 4, QTableWidgetItem(status_text))
                # 状态变化时重建该行的操作按钮
                self.task_table.removeCellWidget(row, 6)
            
            # 下载类型
            download_type = task.download_type.value if task.download_type else "-"
            item = self.task_table.item(row, 5)
            if item is None or item.text() != download_type:
                self.task_table.setItem(row, 5, QTableWidgetItem(download_type))
            
            # 操作按钮 - 已重建或缺失时重新创建
            if self.task_table.cellWidget(row, 6) is None:
                self._create_action_widget(row, task)
    
    def _create_action_widget(self, row: int, task):
        """为任务行创建操作按钮（仅首次或状态变化时调用）"""
        action_widget = QWidget()
        action_widget.setStyleSheet("background-color: transparent;")
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 2, 4, 2)
        action_layout.setSpacing(4)
        
        status = task.get_status()
        
        def make_btn(text: str) -> QPushButton:
            btn = QPushButton(text)
            btn.setObjectName("secondary")
            btn.setFixedSize(40, 20)
            btn.setStyleSheet("font-size: 14px; font-weight: 500;color: gray;padding: 0px;")
            return btn
        
        # 下载中或转码中：显示暂停和取消按钮
        if status in [DownloadStatus.DOWNLOADING, DownloadStatus.TRANSCODING]:
            pause_btn = make_btn("暂停")
            pause_btn.clicked.connect(lambda checked, tid=task.task_id: self.pause_task(tid))
            action_layout.addWidget(pause_btn)
            
            cancel_btn = make_btn("取消")
            cancel_btn.clicked.connect(lambda checked, tid=task.task_id: self.cancel_task(tid))
            action_layout.addWidget(cancel_btn)
        
        # 等待中或已暂停：只显示取消按钮
        elif status in [DownloadStatus.PENDING, DownloadStatus.PAUSED]:
            cancel_btn = make_btn("取消")
            cancel_btn.clicked.connect(lambda checked, tid=task.task_id: self.cancel_task(tid))
            action_layout.addWidget(cancel_btn)
        
        # 下载完成 / 失败 / 其他：显示复制链接和删除按钮
        else:
            copy_btn = make_btn("复制")
            copy_btn.clicked.connect(lambda checked, t=task: self.copy_link(t))
            action_layout.addWidget(copy_btn)
            
            delete_btn = make_btn("删除")
            delete_btn.clicked.connect(lambda checked, tid=task.task_id: self.delete_task(tid))
            action_layout.addWidget(delete_btn)
        
        action_layout.addStretch()
        self.task_table.setCellWidget(row, 6, action_widget)
    
    def pause_task(self, task_id: int):
        """暂停任务"""
        if self.task_manager.pause_task(task_id):
            self.logger.info(f"任务 {task_id} 已暂停")
            self.refresh_task_list()
    
    def cancel_task(self, task_id: int):
        """取消任务"""
        reply = QMessageBox.question(
            self,
            "确认",
            f"确定要取消任务 {task_id} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.task_manager.cancel_task(task_id):
                self.logger.info(f"任务 {task_id} 已取消")
                self.refresh_task_list()
    
    def delete_task(self, task_id: int):
        """删除任务记录"""
        reply = QMessageBox.question(
            self,
            "确认",
            f"确定要删除任务 {task_id} 的记录吗？\n（不会删除已下载的文件）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.task_manager.remove_task(task_id):
                self.logger.info(f"任务 {task_id} 记录已删除")
                self.refresh_task_list()
                QMessageBox.information(self, "成功", f"任务 {task_id} 已删除！")
    
    def copy_link(self, task):
        """复制下载链接"""
        clipboard = QApplication.clipboard()
        clipboard.setText(task.url)
        QMessageBox.information(self, "成功", "链接已复制到剪贴板！")

    def clear_completed_tasks(self):
        """清空已完成的任务"""
        completed_tasks = self.task_manager.get_tasks_by_status(DownloadStatus.COMPLETED)

        if not completed_tasks:
            QMessageBox.information(self, "提示", "没有已完成的任务需要清空")
            return

        reply = QMessageBox.question(
            self,
            "确认",
            f"确定要清空 {len(completed_tasks)} 个已完成的任务记录吗？\n（不会删除已下载的文件）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            count = 0
            for task in completed_tasks:
                if self.task_manager.remove_task(task.task_id):
                    count += 1

            self.logger.info(f"已清空 {count} 个已完成任务")
            self.refresh_task_list()
            QMessageBox.information(self, "成功", f"已清空 {count} 个已完成的任务！")
    
    def on_progress_update(self, task_id: int, progress: float):
        """进度更新回调：当前 UI 依赖定时刷新，此回调保留用于后续接入
        即时进度更新（如信号驱动刷新），避免改动回调注册机制"""
        pass  # 由定时刷新处理
    
    def browse_save_directory(self):
        """浏览保存目录"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择保存目录",
            self.config.get_save_directory()
        )
        if directory:
            self.save_dir_input.setText(directory)
    
    def browse_cookies_file(self):
        """浏览 cookies 文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Cookies 文件",
            "",
            "文本文件 (*.txt);;所有文件 (*)"
        )
        if file_path:
            self.cookies_input.setText(file_path)
    
    def save_settings(self):
        """保存设置"""
        try:
            # 保存下载目录
            save_dir = self.save_dir_input.text()
            self.config.set('download', 'save_directory', save_dir)
            
            # 保存最大并发数
            max_concurrent = self.max_concurrent_spin.value()
            self.task_manager.update_max_concurrent_tasks(max_concurrent)
            
            # 保存 cookies 文件
            cookies_file = self.cookies_input.text()
            self.config.set('cookies', 'cookies_file', cookies_file)

            # 保存转码选项
            convert_to_mp4 = self.convert_to_mp4_checkbox.isChecked()
            self.config.set_convert_to_mp4(convert_to_mp4)

            # 保存 Webhook 端口
            webhook_port = self.webhook_port_spin.value()
            old_port = self.config.get_webhook_port()
            self.config.set_webhook_port(webhook_port)

            # 如果端口改变，提示用户重启应用
            if webhook_port != old_port:
                QMessageBox.information(
                    self,
                    "提示",
                    "Webhook 端口已修改，需要重启应用才能生效！"
                )
            
            self.logger.info("设置已保存")
            QMessageBox.information(self, "成功", "设置已保存！")
        except Exception as e:
            self.logger.error(f"保存设置失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"保存设置失败: {str(e)}")
    
    def reset_settings(self):
        """重置设置"""
        reply = QMessageBox.question(
            self,
            "确认",
            "确定要重置所有设置为默认值吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.config.reset_to_default()
            
            # 更新界面
            self.save_dir_input.setText(self.config.get_save_directory())
            self.max_concurrent_spin.setValue(self.config.get_max_concurrent_tasks())
            self.cookies_input.setText(self.config.get_cookies_file())
            self.convert_to_mp4_checkbox.setChecked(self.config.get_convert_to_mp4())
            self.webhook_port_spin.setValue(self.config.get_webhook_port())
            
            self.logger.info("设置已重置")
            QMessageBox.information(self, "成功", "设置已重置为默认值！")
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        try:
            # 停止定时刷新
            if hasattr(self, 'refresh_timer'):
                self.refresh_timer.stop()

            # 停止 Webhook 服务器
            if hasattr(self, 'webhook_server'):
                self.webhook_server.stop()

            # 关闭任务管理器
            if hasattr(self, 'task_manager'):
                self.task_manager.shutdown()

            self.logger.info("桌面端应用关闭")
            event.accept()
        except Exception as e:
            self.logger.error(f"关闭应用时出错: {str(e)}")
            event.accept()  # 即使出错也要接受关闭事件


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 设置应用程序字体 - 使用现代字体
    font = QFont("Microsoft YaHei UI", 10)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)
    
    # 创建并显示主窗口
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
