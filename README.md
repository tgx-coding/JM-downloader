# JM Downloader By Python v0.1.0

## 前言

> [!WARNING]
> 爱护jm，不要爬那么多本，西门
> -- 官网地址: https://18comic.vip

### 介绍

- 这是一个简单的flask 应用,让你可以轻松的用api的形式下载jm的本子

- 本项目依赖: [Python API For JMComic (禁漫天堂)](https://github.com/hect0x7/JMComic-Crawler-Python/tree/master), python>=3.7 [戳我下载](https://www.python.org/downloads/)

- 源库中封装了一个flask api 但本程序选择仅调用下载方法并重新编写一份

### 食用方法

1. 选择一个合适的目录并运行:

```shell
git clone --depth=1 https://github.com/tgx-coding/JM-downloader.git

cd JM-downloader

pip install -r requirements.txt
```

2. 然后执行
`python app.py`

3. 如果看到类似如下输出则证明运行成功:

```
INFO:root:JM Downloader By Python v0.1.0
INFO:root:获取当前路径并写入...
INFO:root:已更新 .env 文件中的 JM_BASE_DIR 为: /your/path
INFO:root:服务启动，执行首次清理...
INFO:root:检查密码配置...
WARNING:root:当前是默认密码，建议手动在.env文件中更改
INFO:root:内存使用: 39.18 MB (0.12%)
INFO:root:内存监控线程已启动
INFO:root:定时重启线程已启动
 * Serving Flask app 'app'
 * Debug mode: off
INFO:werkzeug:WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:8000
 * Running on http://198.18.0.1:8000
INFO:werkzeug:Press CTRL+C to quit
```

### 注意事项
- 塞了简单的配置文件，如需自己更改可 [戳此查看](https://github.com/hect0x7/JMComic-Crawler-Python/blob/master/assets/docs/sources/option_file_syntax.md)
- api会每隔一小时删除一次工作目录下除了long和pdf文件夹的所有文件夹
- 脚本有简单的崩溃重启，非正常退出(0 code)会重新执行命令

### 原理
- 使用Flask创建一个简单的webapi，并在node中用fetch请求和捕获异常
- 启动后本地地址应为GET http://127.0.0.1:8000/jmd?jm=
- pdf请求地址为GET http://127.0.0.1:8000/jmdp?jm=
- 检查status的地址为GET http://127.0.0.1:8000/
- 查看当前内存使用量 GET http://127.0.0.1:8000/memory
- 触发垃圾回收: POST http://127.0.0.1:8000/gc 
- 文件清理: POST http://127.0.0.1:8000/cleanup
- 停止脚本: POST http://127.0.0.1:8000/stop
- jmcomic库会先把本子下载，再进行长图拼接
- v0.1.0更新:支持多线程下载，传参时传入多个参并用,(逗号)分割即可

## 许可证
本项目使用[MIT](https://zh.wikipedia.org/zh-hk/MIT%E8%A8%B1%E5%8F%AF%E8%AD%89)作为开源许可证