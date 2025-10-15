# Copymanga Downloader
基于 Copymanga API 的控制台漫画下载工具

<img width="844" height="262" alt="image" src="https://github.com/user-attachments/assets/9b949bd5-b220-4ce1-88eb-73c4a35a3141" />

## 尚未完成
如需试用，需要在脚本运行目录补全bin目录，以及文件  
 - bin\curl
 - bin\zip

脚本工作后会生成数据目录  
 - db.nosync 漫画元数据与文件数据库
 - dl.nosync 漫画本地文件下载根目录
 - 例 db.nosync\漫画ID.db
 - 例 dl.nosync\漫画NAME\\*.webp

## 脚本依赖
 - python -m pip install sqlalchemy spdlog requests  
 - spdlog需要本地编译(windows要求安装msvc)

## 当前支持的功能
 - 漫画搜索
 - 漫画更新
 - 漫画下载(遵循API请求次数)
 - 本地缺失文件检查
 - 标记用户手动删除文件
 - 自动使用系统网络代理

## 设计中功能
 - 自动CBZ打包(单行本/章节数分割/文件数分割)
 - 控制台增加漫画(目前需要手动在脚本内定义漫画ID)
