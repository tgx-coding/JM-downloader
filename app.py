# app.py
import jmcomic
from flask import Flask, request, abort, send_file,  jsonify
import os, hmac
import shutil
import logging
import threading
# import time
import gc
import psutil
import tracemalloc
from functools import wraps
from dotenv import load_dotenv
from pathlib import Path
from dotenv import dotenv_values, set_key

logging.basicConfig(level=logging.INFO)
# 加载环境变量
load_dotenv()

# Flask 初始化
app = Flask(__name__)

# 全局配置
JM_BASE_DIR = os.getenv('JM_BASE_DIR', 'C:/a/b/your/path')
EXCLUDE_FOLDER = os.getenv('JM_EXCLUDE_FOLDER', 'long')
EXCLUDE_FOLDER_PDF = os.getenv('JM_EXCLUDE_FOLDER_PDF', 'pdf')
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
    # 主动创建两个目录
    os.makedirs('long', exist_ok=True)
    os.makedirs('pdf', exist_ok=True)

    # 写回 .env 文件
    for key, value in env_vars.items():
        set_key(env_path, key, value)

    logging.info(f"已更新 .env 文件中的 JM_BASE_DIR 为: {current_dir}")



# 文件夹清理函数
def cleanup_folders():
    """清理除指定文件夹外的所有目录"""
    if not os.path.exists(JM_BASE_DIR):
        logging.warning(f"目录不存在: {JM_BASE_DIR}")
        return

    for item in os.listdir(JM_BASE_DIR):
        item_path = os.path.join(JM_BASE_DIR, item)
        if os.path.isdir(item_path) and item not in [EXCLUDE_FOLDER, EXCLUDE_FOLDER_PDF]:
            try:
                shutil.rmtree(item_path)
                logging.info(f"已删除: {item_path}")
            except Exception as e:
                logging.error(f"删除失败: {item_path} - {str(e)}")

# 下载函数
def download_album(jm_id):
    """下载专辑并返回是否成功"""
    try:
        option = jmcomic.create_option_by_file(OPTION_YML_PATH)
        jmcomic.download_album(jm_id, option)
        return True
    except Exception as e:
        logging.error(f"下载失败: {str(e)}")
        return False

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
@app.route('/jmd', methods=['GET'])
def get_image():
    jm_id = request.args.get('jm', type=int)
    if not jm_id or jm_id <= 0:
        abort(400, description="参数 jm 必须为正整数")

    image_path = os.path.join(IMAGE_FOLDER, f"{jm_id}.png")

    if not os.path.exists(image_path):
        if not download_album(jm_id):
            abort(503, description="下载失败")
        
        if not os.path.exists(image_path):
            abort(404, description="资源下载后仍未找到")

    return send_file(image_path, mimetype='image/png')

@app.route('/jmdp', methods=['GET'])
def get_pdf():
    jm_id = request.args.get('jm', type=int)
    if not jm_id or jm_id <= 0:
        abort(400, description="参数 jm 必须为正整数")

    pdf_path = os.path.join(PDF_FOLDER, f"{jm_id}.pdf")

    if not os.path.exists(pdf_path):
        if not download_album(jm_id):
            abort(503, description="下载失败")
        
        if not os.path.exists(pdf_path):
            abort(404, description="资源下载后仍未找到")

    return send_file(pdf_path, mimetype='application/pdf')

@app.route('/cleanup', methods=['POST'])
@admin_required
def cleanup():
    """手动触发清理"""
    cleanup_folders()
    return jsonify(msg="清理完成")


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

@app.route('/gc', methods=['POST'])
@admin_required
def trigger_gc():
    """手动触发垃圾回收"""
    collected = gc.collect()
    return jsonify(msg=f"垃圾回收完成，释放了 {collected} 个对象")

@app.route('/')
def return_status():
    return 'api running!'

# 主程序
if __name__ == '__main__':
    update_jm_base_dir_in_env()
    logging.info("获取当前路径并写入...")

    configure_logging()
    logging.info("服务启动，执行首次清理...")
    cleanup_folders()

    pswd = _get_admin_secret()
    if pswd == 'password':
        logging.warning('当前是默认密码，建议手动在.env文件中更改')
    
    # 启动内存监控线程
    monitor_thread = threading.Thread(target=memory_monitor, daemon=True)
    monitor_thread.start()
    logging.info("内存监控线程已启动")
    
    try:
        app.run(
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