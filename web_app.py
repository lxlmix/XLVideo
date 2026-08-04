import json
import os
import re
import shutil
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

    # 统一使用配置中的保存目录，避免与 config.get_save_directory() 两套基准不一致
    DATA_DIR = config.get_save_directory()
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
        data = request.get_json(silent=True) or {}

        url = (data.get('url') or '').strip()
        custom_name = (data.get('custom_name') or '').strip()

        if not url:
            return jsonify({
                'success': False,
                'error': '请输入视频链接'
            }), 400

        # 构造下载请求头（可选）：任务级覆盖 > 全局设置 > 不附加
        headers = {}
        task_ua = (data.get('user_agent') or '').strip()
        task_ref = (data.get('referer') or '').strip()
        if task_ua:
            headers['User-Agent'] = task_ua
        elif config.get_user_agent():
            headers['User-Agent'] = config.get_user_agent()
        if task_ref:
            headers['Referer'] = task_ref
        elif config.get_referer():
            headers['Referer'] = config.get_referer()

        try:
            task = task_manager.add_task(url, custom_name, headers=headers)
            logger.info(f"Web 端添加任务: {task.task_id}, headers={list(headers.keys())}")

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
            'allowed_directories': config.get_allowed_directories(),
            'max_concurrent_tasks': config.get_max_concurrent_tasks(),
            'cookies_file': config.get_cookies_file(),
            'convert_to_mp4': config.get_convert_to_mp4(),
            'user_agent': config.get_user_agent(),
            'referer': config.get_referer()
        }
        return jsonify({
            'success': True,
            'settings': settings
        })

    @app.route('/api/settings', methods=['POST'])
    def save_settings():
        """保存设置"""
        data = request.get_json(silent=True) or {}

        try:
            # 保存下载目录：必须是 docker 镜像内可访问的目录（白名单前缀），避免填写宿主机无法访问的路径
            if 'save_directory' in data:
                save_dir = str(data['save_directory']).strip()
                if not save_dir:
                    return jsonify({'success': False, 'error': '保存目录不能为空'}), 400
                allowed = config.get_allowed_directories()
                if not any(save_dir == d or save_dir.startswith(d.rstrip('/') + '/') for d in allowed):
                    return jsonify({
                        'success': False,
                        'error': f'保存目录不可访问，请选择镜像内已挂载的目录：{", ".join(allowed)}'
                    }), 400
                config.set('download', 'save_directory', save_dir)

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

            # 保存可选请求头（防盗链站点用）
            if 'user_agent' in data:
                config.set_user_agent(data['user_agent'])
            if 'referer' in data:
                config.set_referer(data['referer'])

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
        """获取日志（最后 100 行，从文件尾部读取，避免全量载入内存）"""
        try:
            log_file = logger.log_file if hasattr(logger, 'log_file') else 'logs/xlvideo.log'
            lines = []
            # 从文件末尾向前读取，最多取 100 行
            with open(log_file, 'rb') as f:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                block_size = 8192
                data = b''
                while file_size > 0 and len(lines) < 100:
                    read_size = min(block_size, file_size)
                    f.seek(file_size - read_size)
                    block = f.read(read_size)
                    data = block + data
                    file_size -= read_size
                    lines = data.split(b'\n')
                lines = lines[-100:] if len(lines) > 100 else lines
            log_content = b'\n'.join(lines).decode('utf-8', errors='replace')
            
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
    
    # ==================== 文件管理（批量重命名）====================

    def _validate_path(path):
        """校验路径在白名单允许的目录内，防止路径穿越"""
        if not path:
            return None, '路径不能为空'
        try:
            real = os.path.realpath(path)
        except Exception:
            return None, '无效路径'
        for allowed in config.get_allowed_directories():
            allowed_real = os.path.realpath(allowed)
            if real == allowed_real or real.startswith(allowed_real + os.sep):
                return real, None
        return None, '路径不在允许的目录范围内'

    def _split_filename(filename):
        """将文件名拆分为 (主名, 扩展名)，扩展名不含点"""
        base, ext = os.path.splitext(filename)
        return base, ext[1:] if ext else ''

    def _compute_new_name(mode, filename, params, index):
        """
        根据批量重命名模式计算新文件名（仅主名部分，不含扩展名）
        返回 (new_base, new_ext)
        """
        base, ext = _split_filename(filename)

        if mode == 'find_replace':
            find = params.get('find', '')
            replace = params.get('replace', '')
            if find:
                new_base = base.replace(find, replace)
            else:
                new_base = base
            return new_base, ext

        elif mode == 'add_prefix':
            prefix = params.get('prefix', '')
            return prefix + base, ext

        elif mode == 'add_suffix':
            suffix = params.get('suffix', '')
            return base + suffix, ext

        elif mode == 'sequential':
            fmt = params.get('format', '文件_{seq}')
            start = int(params.get('start', 1))
            step = int(params.get('step', 1))
            pad = int(params.get('pad', 2))
            seq = start + index * step
            # 支持 {seq} 占位符，也支持 {seq:0Nd} 格式
            if '{seq' in fmt:
                try:
                    new_base = fmt.format(seq=seq)
                except Exception:
                    new_base = fmt.replace('{seq}', str(seq).zfill(pad))
            else:
                new_base = fmt + str(seq).zfill(pad)
            return new_base, ext

        elif mode == 'delete_chars':
            chars = params.get('chars', '')
            new_base = base
            for c in chars:
                new_base = new_base.replace(c, '')
            return new_base, ext

        elif mode == 'case_convert':
            case = params.get('case', 'lower')
            if case == 'lower':
                new_base = base.lower()
            elif case == 'upper':
                new_base = base.upper()
            elif case == 'capitalize':
                new_base = base[:1].upper() + base[1:].lower() if base else base
            elif case == 'title':
                new_base = base.title()
            else:
                new_base = base
            return new_base, ext

        elif mode == 'regex_replace':
            pattern = params.get('pattern', '')
            replacement = params.get('replacement', '')
            if pattern:
                try:
                    new_base = re.sub(pattern, replacement, base)
                except re.error:
                    new_base = base
            else:
                new_base = base
            return new_base, ext

        return base, ext

    @app.route('/api/files/list', methods=['GET'])
    def list_files():
        """列出指定目录下的子目录和文件"""
        req_path = request.args.get('path', '').strip()

        allowed = config.get_allowed_directories()

        # 未指定路径时，返回白名单根目录列表供前端选择
        if not req_path:
            dirs = []
            for d in allowed:
                if os.path.isdir(d):
                    dirs.append({
                        'name': os.path.basename(d) or d,
                        'path': d,
                        'type': 'directory'
                    })
            return jsonify({'success': True, 'directories': dirs, 'files': [], 'current': ''})

        real_path, err = _validate_path(req_path)
        if err:
            return jsonify({'success': False, 'error': err}), 400

        if not os.path.isdir(real_path):
            return jsonify({'success': False, 'error': '不是有效目录'}), 400

        try:
            entries = sorted(os.listdir(real_path))
        except PermissionError:
            return jsonify({'success': False, 'error': '无权限访问该目录'}), 403

        directories = []
        files = []
        for name in entries:
            full = os.path.join(real_path, name)
            if os.path.isdir(full):
                directories.append({
                    'name': name,
                    'path': full,
                    'type': 'directory'
                })
            elif os.path.isfile(full):
                stat = os.stat(full)
                base, ext = _split_filename(name)
                files.append({
                    'name': name,
                    'path': full,
                    'base': base,
                    'ext': ext,
                    'size': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                    'type': 'file'
                })

        return jsonify({
            'success': True,
            'directories': directories,
            'files': files,
            'current': real_path
        })

    @app.route('/api/files/rename', methods=['POST'])
    def rename_single_file():
        """单文件重命名 — 文件名与扩展名分开编辑"""
        data = request.get_json(silent=True) or {}
        old_path = (data.get('path') or '').strip()
        new_base = (data.get('new_base') or '').strip()
        new_ext = (data.get('new_ext') or '').strip().lstrip('.')

        if not old_path or not new_base:
            return jsonify({'success': False, 'error': '文件路径和新文件名不能为空'}), 400

        real_old, err = _validate_path(old_path)
        if err:
            return jsonify({'success': False, 'error': err}), 400

        if not os.path.exists(real_old):
            return jsonify({'success': False, 'error': '文件不存在'}), 404

        # 构造新路径（同目录下）
        parent = os.path.dirname(real_old)
        new_name = new_base if not new_ext else f'{new_base}.{new_ext}'
        # 净化文件名，防止路径穿越和非法字符
        new_name = re.sub(r'[\\/:*?"<>|]', '_', new_name).strip()
        if not new_name:
            return jsonify({'success': False, 'error': '新文件名无效'}), 400

        new_path = os.path.join(parent, new_name)

        if os.path.exists(new_path) and os.path.realpath(new_path) != real_old:
            return jsonify({'success': False, 'error': f'目标文件已存在: {new_name}'}), 409

        try:
            os.rename(real_old, new_path)
            logger.info(f"重命名: {os.path.basename(real_old)} -> {new_name}")
            return jsonify({
                'success': True,
                'old_path': real_old,
                'new_path': new_path,
                'new_name': new_name
            })
        except Exception as e:
            logger.error(f"重命名失败: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/files/batch-rename', methods=['POST'])
    def batch_rename_files():
        """
        批量重命名 — 支持 7 种模式
        Body: { mode, files: [path...], params: {...}, preview: bool }
        """
        data = request.get_json(silent=True) or {}
        mode = data.get('mode', '')
        file_list = data.get('files', [])
        params = data.get('params', {})
        preview_only = data.get('preview', False)

        valid_modes = ['find_replace', 'add_prefix', 'add_suffix', 'sequential',
                       'delete_chars', 'case_convert', 'regex_replace']
        if mode not in valid_modes:
            return jsonify({'success': False, 'error': f'不支持的模式: {mode}'}), 400

        if not file_list or not isinstance(file_list, list):
            return jsonify({'success': False, 'error': '请选择至少一个文件'}), 400

        # 校验所有路径并收集文件名
        validated = []
        for fp in file_list:
            real, err = _validate_path(fp)
            if err:
                return jsonify({'success': False, 'error': f'路径校验失败: {fp} - {err}'}), 400
            if not os.path.isfile(real):
                return jsonify({'success': False, 'error': f'文件不存在: {fp}'}), 404
            validated.append(real)

        # 计算新文件名
        previews = []
        used_names = set()
        for i, real_path in enumerate(validated):
            old_name = os.path.basename(real_path)
            new_base, new_ext = _compute_new_name(mode, old_name, params, i)
            new_name = new_base if not new_ext else f'{new_base}.{new_ext}'
            new_name = re.sub(r'[\\/:*?"<>|]', '_', new_name).strip()
            if not new_name:
                new_name = old_name  # 安全兜底

            parent = os.path.dirname(real_path)
            new_path = os.path.join(parent, new_name)
            previews.append({
                'old_name': old_name,
                'new_name': new_name,
                'old_path': real_path,
                'new_path': new_path,
                'changed': os.path.basename(new_path) != old_name
            })

        # 预览模式：只返回结果不执行
        if preview_only:
            return jsonify({'success': True, 'previews': previews})

        # 执行重命名 — 先检查冲突（新名称与现有文件冲突且不是自身）
        for p in previews:
            if p['new_path'] != p['old_path'] and os.path.exists(p['new_path']):
                # 检查是否在本次批量中会产生同名（不同路径冲突）
                return jsonify({
                    'success': False,
                    'error': f'目标文件已存在: {p["new_name"]}（来源: {p["old_name"]}）'
                }), 409

        # 执行重命名 — 防止批量内名称碰撞
        # 如果两个文件的新名称在同一目录下相同，在 used_names 中检测
        rename_plan = []
        seen_targets = {}
        for p in previews:
            if not p['changed']:
                continue
            key = p['new_path']
            if key in seen_targets:
                return jsonify({
                    'success': False,
                    'error': f'批量内名称冲突: {p["old_name"]} 和 {seen_targets[key]} 的新名称都是 {p["new_name"]}'
                }), 409
            seen_targets[key] = p['old_name']
            rename_plan.append(p)

        renamed = []
        errors = []
        for p in rename_plan:
            try:
                os.rename(p['old_path'], p['new_path'])
                renamed.append({'old': p['old_name'], 'new': p['new_name']})
            except Exception as e:
                errors.append({'old': p['old_name'], 'error': str(e)})

        logger.info(f"批量重命名完成: {len(renamed)} 成功, {len(errors)} 失败, 模式={mode}")

        return jsonify({
            'success': len(errors) == 0,
            'renamed': renamed,
            'errors': errors,
            'total': len(rename_plan)
        })

    return app


def main():
    """主函数"""
    app = create_app()
    # 默认只监听本机，避免局域网内无鉴权访问；部署到公网/局域网时用 XLVIDEO_HOST 覆盖
    host = os.getenv('XLVIDEO_HOST', '127.0.0.1')
    port = int(os.getenv('XLVIDEO_PORT', '5000'))
    app.run(host=host, port=port, debug=False)


if __name__ == '__main__':
    main()
