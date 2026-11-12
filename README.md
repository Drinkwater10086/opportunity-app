# AI 机会研究台

基于 FastAPI 的本地数据采集和 AI 机会分析原型。

## 本机运行

需要 Python 3.12。在项目目录运行：

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

在浏览器访问 http://127.0.0.1:8000 。首次访问需创建管理员账号。模型密钥通过应用设置输入，不应提交到仓库。运行数据保存在 data/，不包含在本代码包中。

目前为本机原型，未完成公网部署加固；不要直接暴露到公网。GitHub Pages 不运行 Python 后端。
