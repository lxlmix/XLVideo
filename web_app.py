import json
import os
from datetime import datetime

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

from xlvideo.config import ConfigManager
from xlvideo.logger import LogManager
from xlvideo.task_manager import TaskManager


def create_app():
    """创建 Flask 应用"""
    app = Flask(__name__)
    CORS(app)  # 启用跨域支持
    
    # 初始化管理器
    config = ConfigManager()
    logger = LogManager()
    task_manager = TaskManager()
    
    logger.info("Web 端应用启动")

    # ==================== 配置常量 ====================

    DATA_DIR = os.getenv('DATA_DIR', 'downloads')
    os.makedirs(DATA_DIR, exist_ok=True)

    # ==================== 辅助函数 ====================

    def save_to_txt(record: dict):
        """保存接收到的数据到 txt 文件"""
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
        """处理 webhook 接收到的数据"""
        action = data.get('action')
        payload = data.get('data')
        tab_id = data.get('tabId')

        if action not in ('catch', 'addKey'):
            return jsonify({"error": f"Unsupported action: {action}"}), 400

        logger.info(f"Received {action} from tab {tab_id}")

        save_to_txt(data)

        if action == 'catch':
            if not isinstance(payload, dict):
                return jsonify({"error": "Expected data to be an object for action 'catch'"}), 400

            title = payload.get('title', '')
            url = payload.get('url', '')
            name = payload.get('name')
            size = payload.get('size')
            headers = payload.get('requestHeaders', {})

            logger.info(f"Captured file: name={name}, url={url}, size={size}, referer={headers.get('referer')}")

            if url:
                try:
                    task = task_manager.add_task(url, title if title else '')
                    logger.info(f"✓ 下载任务已添加 - Task ID: {task.task_id}, Title: {title}")
                    return jsonify({
                        "status": "ok",
                        "message": "Catch data received and download task added",
                        "task_id": task.task_id
                    }), 200
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"✗ 添加下载任务失败: {error_msg}")
                    return jsonify({
                        "status": "warning",
                        "message": "Catch data received but failed to add download task",
                        "error": error_msg
                    }), 200
            else:
                return jsonify({"status": "ok", "message": "Catch data received (no URL)"}), 200

        elif action == 'addKey':
            if not isinstance(payload, str):
                return jsonify({"error": "Expected data to be a base64 string for action 'addKey'"}), 400
            logger.info(f"Received key (base64 length {len(payload)})")
            return jsonify({"status": "ok", "message": "Key data received"}), 200

        return jsonify({"error": "Internal error"}), 500

    # ==================== 路由定义 ====================
    
    @app.route('/')
    def index():
        """主页 - 渲染 HTML 模板"""
        return render_template('index.html')

    @app.route('/', methods=['POST'])
    def webhook_root():
        """Webhook 根路径 - 接收浏览器插件数据"""
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 415
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON body"}), 400
        return process_webhook_data(data)

    @app.route('/webhook', methods=['POST'])
    def webhook():
        """Webhook 接口 - 接收浏览器插件数据"""
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 415
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON body"}), 400
        return process_webhook_data(data)

    @app.route('/health', methods=['GET'])
    def health_check():
        """健康检查接口"""
        return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()}), 200

    @app.route('/api/tasks', methods=['GET'])
    def get_tasks():
        """获取所有任务列表"""
        tasks = task_manager.get_all_tasks()
        tasks_data = [task.to_dict() for task in tasks]
        return jsonify({
            'success': True,
            'tasks': tasks_data
        })
    
    @app.route('/api/tasks', methods=['POST'])
    def add_task():
        """添加新任务"""
        data = request.json
        
        url = data.get('url', '').strip()
        custom_name = data.get('custom_name', '').strip()
        
        if not url:
            return jsonify({
                'success': False,
                'error': '请输入视频链接'
            }), 400
        
        try:
            task = task_manager.add_task(url, custom_name)
            logger.info(f"Web 端添加任务: {task.task_id}")
            
            return jsonify({
                'success': True,
                'task': task.to_dict()
            })
        except Exception as e:
            logger.error(f"添加任务失败: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/tasks/<int:task_id>/pause', methods=['POST'])
    def pause_task(task_id):
        """暂停任务"""
        if task_manager.pause_task(task_id):
            return jsonify({
                'success': True,
                'message': f'任务 {task_id} 已暂停'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'无法暂停任务 {task_id}'
            }), 400
    
    @app.route('/api/tasks/<int:task_id>/cancel', methods=['POST'])
    def cancel_task(task_id):
        """取消任务"""
        if task_manager.cancel_task(task_id):
            return jsonify({
                'success': True,
                'message': f'任务 {task_id} 已取消'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'无法取消任务 {task_id}'
            }), 400

    @app.route('/api/tasks/clear-completed', methods=['POST'])
    def clear_completed_tasks():
        """清空所有已完成的任务记录"""
        try:
            from xlvideo.engine import DownloadStatus

            tasks = task_manager.get_all_tasks()
            # 修复：使用枚举值进行比较
            completed_tasks = [task for task in tasks if task.get_status() == DownloadStatus.COMPLETED]

            logger.info(f"找到 {len(completed_tasks)} 个已完成的任务，开始清理...")

            count = 0
            for task in completed_tasks:
                try:
                    if task_manager.remove_task(task.task_id):
                        count += 1
                        logger.debug(f"成功删除任务 {task.task_id}")
                    else:
                        logger.warning(f"删除任务 {task.task_id} 失败，可能状态不允许")
                except Exception as e:
                    logger.error(f"删除任务 {task.task_id} 时出错: {str(e)}")

            logger.info(f"Web 端清空了 {count} 个已完成的任务记录")
            return jsonify({
                'success': True,
                'count': count,
                'message': f'已清空 {count} 个已完成的任务'
            })
        except Exception as e:
            logger.error(f"清空已完成任务失败: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
    def delete_task(task_id):
        """删除任务记录"""
        if task_manager.remove_task(task_id):
            logger.info(f"Web 端删除任务记录: {task_id}")
            return jsonify({
                'success': True,
                'message': f'任务 {task_id} 已删除'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'无法删除任务 {task_id}'
            }), 400
    
    @app.route('/api/settings', methods=['GET'])
    def get_settings():
        """获取设置"""
        settings = {
            'save_directory': config.get_save_directory(),
            'max_concurrent_tasks': config.get_max_concurrent_tasks(),
            'cookies_file': config.get_cookies_file()
        }
        return jsonify({
            'success': True,
            'settings': settings
        })
    
    @app.route('/api/settings', methods=['POST'])
    def save_settings():
        """保存设置"""
        data = request.json
        
        try:
            # 保存下载目录
            if 'save_directory' in data:
                config.set('download', 'save_directory', data['save_directory'])
            
            # 保存最大并发数
            if 'max_concurrent_tasks' in data:
                max_concurrent = int(data['max_concurrent_tasks'])
                task_manager.update_max_concurrent_tasks(max_concurrent)
            
            # 保存 cookies 文件
            if 'cookies_file' in data:
                config.set('cookies', 'cookies_file', data['cookies_file'])

            # 保存转换为MP4选项
            if 'convert_to_mp4' in data:
                config.set_convert_to_mp4(bool(data['convert_to_mp4']))

            logger.info("Web 端设置已保存")
            
            return jsonify({
                'success': True,
                'message': '设置已保存'
            })
        except Exception as e:
            logger.error(f"保存设置失败: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/settings/reset', methods=['POST'])
    def reset_settings():
        """重置设置"""
        try:
            config.reset_to_default()
            logger.info("Web 端设置已重置")
            
            return jsonify({
                'success': True,
                'message': '设置已重置为默认值'
            })
        except Exception as e:
            logger.error(f"重置设置失败: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/logs', methods=['GET'])
    def get_logs():
        """获取日志（最后 100 行）"""
        try:
            log_file = logger.log_file if hasattr(logger, 'log_file') else 'logs/xlvideo.log'
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                last_lines = lines[-100:] if len(lines) > 100 else lines
                log_content = ''.join(last_lines)
            
            return jsonify({
                'success': True,
                'logs': log_content
            })
        except Exception as e:
            logger.error(f"读取日志失败: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    return app


def main():
    """主函数"""
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=False)


if __name__ == '__main__':
    main()
