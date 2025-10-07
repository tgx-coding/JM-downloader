# app.py v0.1.1
import jmcomic
from flask import Flask, request, abort, send_file,  jsonify
import os, hmac
import shutil
import logging
import threading
import sys
# import signal
# import time
import gc
import psutil
import tracemalloc
from functools import wraps
from dotenv import load_dotenv, dotenv_values, set_key
from pathlib import Path

logging.basicConfig(level=logging.INFO)
# 加载环境变量
load_dotenv()

# Flask 初始化
app = Flask(__name__)

# 全局配置
JM_BASE_DIR = os.getenv('JM_BASE_DIR', 'C:/a/b/your/path')
EXCLUDE_FOLDER =  os.getenv('JM_EXCLUDE_FOLDER', 'long'),
EXCLUDE_FOLDER_PDF = os.getenv('JM_EXCLUDE_FOLDER_PDF', 'pdf'),
EXCLUDE_FOLDER_GIT = os.getenv('JM_EXCLUDE_FOLDER_GIT', '.git')

FLASK_HOST = os.getenv('FLASK_HOST', '0.0.0.0')
FLASK_PORT = int(os.getenv('FLASK_PORT', '8000'))

MEMORY_THRESHOLD = float(os.getenv('MEMORY_THRESHOLD', '80.0'))  # 内存使用百分比阈值

# 推导路径
IMAGE_FOLDER = os.path.join(JM_BASE_DIR, 'long')
PDF_FOLDER = os.path.join(JM_BASE_DIR, 'pdf')
OPTION_YML_PATH = os.path.join(JM_BASE_DIR, 'option.yml')

# 内存监控状态
# memory_monitor_running = True
exit_evt = threading.Event()
# 日志配置
def configure_logging():
    log_file_path = os.path.join(JM_BASE_DIR, 'app.log')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file_path, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

# 定时重启函数
def schedule_restart(interval_hours=24):
    """每隔 interval_hours 小时自动重启"""
    while not exit_evt.is_set():
        if exit_evt.wait(interval_hours * 3600):
            break
        logging.info(f"到达定时任务（{interval_hours}h），准备重启 Flask...")
        os.execv(sys.executable, [sys.executable] + sys.argv)

#密码配置校验
def _get_admin_secret() -> str:
    return os.getenv("ADMIN_SECRET", "")

def _verify_admin_pwd() -> bool:
    """常量时间比较，防计时攻击"""
    secret = _get_admin_pwd()
    if not secret:               # 没配密码就永远失败
        return False
    sent = request.json.get("secret", "") if request.is_json else ""
    return hmac.compare_digest(sent.encode(), secret.encode())

def _get_admin_pwd():
    return _get_admin_secret()
#定义一份装饰器
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _verify_admin_pwd():
            abort(403)          # 403 比 401 更模糊，不暴露原因
        return f(*args, **kwargs)
    return wrapper

# 路径获取函数(包含创建long与pdf文件夹)
def update_jm_base_dir_in_env():
    env_path = Path('.env')
    # 读取已有内容（保留其他变量）
    env_vars = dotenv_values(env_path) if env_path.exists() else {}

    # 更新 JM_BASE_DIR 为当前工作目录
    current_dir = Path.cwd().resolve()
    env_vars['JM_BASE_DIR'] = str(current_dir)
    # 主动创建两个目录（基于当前工作目录）
    os.makedirs(current_dir / 'long', exist_ok=True)
    os.makedirs(current_dir / 'pdf', exist_ok=True)

    # 更新运行时的全局变量，保证后续代码使用正确路径
    global JM_BASE_DIR, IMAGE_FOLDER, PDF_FOLDER
    JM_BASE_DIR = str(current_dir)
    IMAGE_FOLDER = os.path.join(JM_BASE_DIR, 'long')
    PDF_FOLDER = os.path.join(JM_BASE_DIR, 'pdf')

    # 写回 .env 文件
    for key, value in env_vars.items():
        set_key(env_path, key, value)

    logging.info(f"已更新 .env 文件中的 JM_BASE_DIR 为: {current_dir}")



# 文件夹清理函数
def cleanup_folders():
    """清理除 long、pdf 及所有隐藏文件夹外的所有目录"""
    if not os.path.exists(JM_BASE_DIR):
        logging.warning(f"目录不存在: {JM_BASE_DIR}")
        return

    exclude_folders = {"long", "pdf"}
    # 允许所有以点开头的隐藏文件夹保留
    for item in os.listdir(JM_BASE_DIR):
        item_path = os.path.join(JM_BASE_DIR, item)
        # 跳过 long、pdf、所有隐藏文件夹（.开头）
        if os.path.isdir(item_path) and item not in exclude_folders and not item.startswith('.'):
            try:
                shutil.rmtree(item_path)
                logging.info(f"已删除: {item_path}")
            except Exception as e:
                logging.error(f"删除失败: {item_path} - {str(e)}")


# 单个下载
def download_album(jm_id):
    """下载专辑并返回是否成功"""
    try:
        option = jmcomic.create_option_by_file(OPTION_YML_PATH)
        jmcomic.download_album(jm_id, option)
        return True
    except Exception as e:
        logging.error(f"下载失败: {str(e)}")
        return False

# 多线程批量下载
def download_album_multi(jm_ids):
    """多线程下载多个专辑，返回 {jm_id: True/False} 字典"""
    results = {}
    threads = []

    def worker(jm_id):
        results[jm_id] = download_album(jm_id)

    for jm_id in jm_ids:
        t = threading.Thread(target=worker, args=(jm_id,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()
    return results

# 内存监控函数
def memory_monitor():
    """必要时触发垃圾回收"""
    process = psutil.Process(os.getpid())

    tracemalloc.start()

    while not exit_evt.is_set():
        try:
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()
            logging.info(f"内存使用: {memory_info.rss / 1024 / 1024:.2f} MB ({memory_percent:.2f}%)")
            if memory_percent > MEMORY_THRESHOLD:
                logging.warning(f"内存使用超过阈值 ({memory_percent:.2f}% > {MEMORY_THRESHOLD}%)，触发垃圾回收")
                gc.collect()
                snapshot = tracemalloc.take_snapshot()
                top_stats = snapshot.statistics('lineno')
                logging.info("内存分配前10:")
                for stat in top_stats[:10]:
                    logging.info(f"  {stat}")
            exit_evt.wait(30)         

        except Exception as e:
            logging.error(f"内存监控错误: {str(e)}")
            exit_evt.wait(60)

    logging.info("memory_monitor 线程正常结束")

# 路由处理

# 支持多 jm_id 下载
@app.route('/jmd', methods=['GET'])
def get_image():
    jm_param = request.args.get('jm')
    if not jm_param:
        abort(400, description="参数 jm 必须为正整数或逗号分隔的正整数")

    # 支持逗号分隔
    jm_ids = [s.strip() for s in jm_param.split(',') if s.strip()]
    try:
        jm_ids = [int(j) for j in jm_ids if int(j) > 0]
    except Exception:
        abort(400, description="参数 jm 必须为正整数或逗号分隔的正整数")
    if not jm_ids:
        abort(400, description="参数 jm 必须为正整数或逗号分隔的正整数")

    # 多于1个则多线程
    if len(jm_ids) == 1:
        jm_id = jm_ids[0]
        image_path = os.path.join(IMAGE_FOLDER, f"{jm_id}.png")
        if not os.path.exists(image_path):
            if not download_album(jm_id):
                abort(503, description="下载失败")
            if not os.path.exists(image_path):
                abort(404, description="资源下载后仍未找到")
        return send_file(image_path, mimetype='image/png')
    else:
        # 只下载 long 文件夹中不存在的 jm_id，已存在的跳过
        to_download = [j for j in jm_ids if not os.path.exists(os.path.join(IMAGE_FOLDER, f"{j}.png"))]
        results = {}
        failed = []
        if to_download:
            results = download_album_multi(to_download)
            failed = [str(j) for j, ok in results.items() if not ok]

        # 检查所有图片是否存在（包含之前已存在和刚下载的）
        missing = [str(j) for j in jm_ids if not os.path.exists(os.path.join(IMAGE_FOLDER, f"{j}.png"))]
        if failed or missing:
            abort(503, description=f"部分下载失败: {','.join(failed+missing)}")

        # 返回所有图片路径列表（所有 jm_id 均应存在）
        files = [os.path.join(IMAGE_FOLDER, f"{j}.png") for j in jm_ids]
        # 打包为zip返回
        import zipfile, io
        mem_zip = io.BytesIO()
        with zipfile.ZipFile(mem_zip, 'w') as zf:
            for f in files:
                zf.write(f, arcname=os.path.basename(f))
        mem_zip.seek(0)
        return send_file(mem_zip, mimetype='application/zip', as_attachment=True, download_name='images.zip')


# 支持多 jm_id 下载 PDF
@app.route('/jmdp', methods=['GET'])
def get_pdf():
    jm_param = request.args.get('jm')
    if not jm_param:
        abort(400, description="参数 jm 必须为正整数或逗号分隔的正整数")

    jm_ids = [s.strip() for s in jm_param.split(',') if s.strip()]
    try:
        jm_ids = [int(j) for j in jm_ids if int(j) > 0]
    except Exception:
        abort(400, description="参数 jm 必须为正整数或逗号分隔的正整数")
    if not jm_ids:
        abort(400, description="参数 jm 必须为正整数或逗号分隔的正整数")

    if len(jm_ids) == 1:
        jm_id = jm_ids[0]
        pdf_path = os.path.join(PDF_FOLDER, f"{jm_id}.pdf")
        if not os.path.exists(pdf_path):
            if not download_album(jm_id):
                abort(503, description="下载失败")
            if not os.path.exists(pdf_path):
                abort(404, description="资源下载后仍未找到")
        return send_file(pdf_path, mimetype='application/pdf')
    else:
        # 只下载 pdf 文件夹中不存在的 jm_id，已存在的跳过
        to_download = [j for j in jm_ids if not os.path.exists(os.path.join(PDF_FOLDER, f"{j}.pdf"))]
        results = {}
        failed = []
        if to_download:
            results = download_album_multi(to_download)
            failed = [str(j) for j, ok in results.items() if not ok]

        # 检查所有 pdf 是否存在（包含之前已存在和刚下载的）
        missing = [str(j) for j in jm_ids if not os.path.exists(os.path.join(PDF_FOLDER, f"{j}.pdf"))]
        if failed or missing:
            abort(503, description=f"部分下载失败: {','.join(failed+missing)}")

        files = [os.path.join(PDF_FOLDER, f"{j}.pdf") for j in jm_ids]
        import zipfile, io
        mem_zip = io.BytesIO()
        with zipfile.ZipFile(mem_zip, 'w') as zf:
            for f in files:
                zf.write(f, arcname=os.path.basename(f))
        mem_zip.seek(0)
        return send_file(mem_zip, mimetype='application/zip', as_attachment=True, download_name='pdfs.zip')


@app.route('/memory', methods=['GET'])
def memory_info():
    """获取当前内存使用信息"""
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    memory_percent = process.memory_percent()
    
    return {
        'rss_mb': memory_info.rss / 1024 / 1024,
        'vms_mb': memory_info.vms / 1024 / 1024,
        'percent': memory_percent
    }

# 管理员需要用的路由，文件清理，停止服务器，内存清理
@app.route('/cleanup', methods=['POST'])
@admin_required
def cleanup():
    """手动触发清理"""
    cleanup_folders()
    return jsonify(msg="清理完成")


@app.route('/gc', methods=['POST'])
@admin_required
def trigger_gc():
    """手动触发垃圾回收"""
    collected = gc.collect()
    return jsonify(msg=f"垃圾回收完成，释放了 {collected} 个对象")

@app.route('/stop', methods=['POST'])
@admin_required
def stop_server():
    """优雅停止 Flask 服务"""
    exit_evt.set()  # 通知后台线程结束
    logging.info("接收到停止请求，准备退出进程...")
    shutdown_func = request.environ.get("werkzeug.server.shutdown")
    if shutdown_func:
        shutdown_func()
    else:
        # 如果不是 werkzeug server，直接强退
        os._exit(0)
    return jsonify(msg="服务正在关闭...")

@app.route('/')
def return_status():
    return 'api running!'

# 主程序
if __name__ == '__main__':
    logging.info("    _____  __       __   ______    ______   __       __  ______   ______   __  __ ")
    logging.info("   /     |/  \\     /  | /      \\  /      \\ /  \\     /  |/      | /      \\ /  |/  |")
    logging.info("   $$$$$ |$$  \\   /$$ |/$$$$$$  |/$$$$$$  |$$  \\   /$$ |$$$$$$/ /$$$$$$  |$$ |$$ |")
    logging.info("      $$ |$$$  \\ /$$$ |$$ |  $$/ $$ |  $$ |$$$  \\ /$$$ |  $$ |  $$ |  $$/ $$ |$$ |")
    logging.info(" __   $$ |$$$$  /$$$$ |$$ |      $$ |  $$ |$$$$  /$$$$ |  $$ |  $$ |      $$ |$$ |")
    logging.info("/  |  $$ |$$ $$ $$/$$ |$$ |   __ $$ |  $$ |$$ $$ $$/$$ |  $$ |  $$ |   __ $$/ $$/ ")
    logging.info("$$ \\__$$ |$$ |$$$/ $$ |$$ \\__/  |$$ \\__$$ |$$ |$$$/ $$ | _$$ |_ $$ \\__/  | __  __ ")
    logging.info("$$    $$/ $$ | $/  $$ |$$    $$/ $$    $$/ $$ | $/  $$ |/ $$   |$$    $$/ /  |/  |")
    logging.info(" $$$$$$/  $$/      $$/  $$$$$$/   $$$$$$/  $$/      $$/ $$$$$$/  $$$$$$/  $$/ $$/ ")
    # logging.info("JM Downloader By Python v0.1.0")
    logging.info("JM Downloader By Python v0.1.1")
    configure_logging() # 配置日志
    logging.info("获取当前路径并写入...")
    update_jm_base_dir_in_env() # 更新路径
    logging.info("服务启动，执行首次清理...")
    cleanup_folders() # 启动时清理
    logging.info("检查密码配置...")
    pswd = _get_admin_secret() # 检查密码
    if pswd == 'password':
        logging.warning('当前是默认密码，建议手动在.env文件中更改')
    
    # 启动内存监控线程
    monitor_thread = threading.Thread(target=memory_monitor, daemon=True)
    monitor_thread.start()
    logging.info("内存监控线程已启动")
    # 启用定时重启
    restart_thread = threading.Thread(target=schedule_restart, args=(24,), daemon=True)
    restart_thread.start()
    logging.info("定时重启线程已启动")
    try:
        app.run(
            threaded=True,
            host=FLASK_HOST,
            port=FLASK_PORT,
            debug=False,
            use_reloader=False
        )
    except KeyboardInterrupt:
        logging.info("接收到中断信号，停止服务...")
    finally:
        exit_evt.set()
        monitor_thread.join(timeout=5)
        logging.info("服务已停止")