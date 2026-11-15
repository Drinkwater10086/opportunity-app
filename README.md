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

## 本地分析新版

登录并采集后，打开 http://127.0.0.1:8000/local 。规则判别、LSA/TF-IDF聚类、评分和评价在本机执行，无需模型密钥。旧版大模型结果保留为对照；本地结果另存独立实验。

- [方法、指标与限制](LOCAL_ANALYSIS.md)
- [参考来源、格式与采集边界](SOURCES.md)
- [赛事要求与当前差距](CONTEST_CHECKLIST.md)
- [内容边界与真实批次实验](CONTEXT_RULES.md)
- [实验离线重放与新批次检验](REPRODUCIBILITY.md)
- [价值同分与权重敏感性](VALUE_DIAGNOSTICS.md)
- [AI协助事实记录草稿（待核实，非最终提交件）](AI_ASSISTANCE_DRAFT.md)

新增V2EX最新公开主题、arXiv当日AI摘要来源。后者仅作技术背景，不单独当作需求机会。订阅源不支持历史全站搜索；图片、PDF及音视频尚未自动转换。

运行测试：`python -m pytest -q`（安装requirements-dev.txt中的测试依赖）。

可选本地E5语义向量已加入对照实验：先按[方法说明](LOCAL_ANALYSIS.md)准备模型和可选依赖，再在本地分析页选择。默认方法仍为LSA；不会自动联网下载、调用付费API或以模型输出代替规则判别。
