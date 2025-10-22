# Copymanga Downloader
基于 Copymanga API & Aria2c RPC 的控制台漫画下载工具
```
Active code page: 65001

00. [ A | 无本地文件 | a_path_word ] 
01. [ B | 543.5 MiB | b_path_word ] 
02. [ C | 无本地文件 | c_path_word ] 
03. [ D | 无本地文件 | d_path_word ] 
04. [ E | 无本地文件 | e_path_word ] 
05. [ F | 无本地文件 | f_path_word ] 


help                     显示命令列表
update [index/all]       更新数据库
download [index/all]     下载文件
detect [index/all]       下载文件
check [index/all]        检查本地文件
show [index]             显示详细信息
mark [index]             标记已下载但不存在的文件
delete [index]           删除数据库
search [keyword]         使用关键词搜索并创建数据库
init [pathword]          使用路径词创建数据库
list                     显示漫画列表
clear                    清除控制台内容
exit                     退出

> 
```

## 尚未完成
如需试用 aria2c 需要在环境变量内可用

脚本工作后会生成数据目录  
 - db.nosync 漫画元数据与文件数据库
 - dl.nosync 漫画本地文件下载根目录
 - 例 db.nosync\漫画路径词.db
 - 例 dl.nosync\漫画名称\分组名称\*.webp

## 脚本依赖
 - python -m pip install sqlalchemy spdlog requests  
 - spdlog 需要本地编译 (windows要求安装msvc)

## 当前支持的功能
 - 见上方命令行示例
 - 下载和请求遵循API次数限制
 - 自动使用系统网络代理

## 设计中功能
 - 自动CBZ打包(单行本/章节数分割/文件数分割)
 - 更新章节同时下载的多线程模式
 - 额外的图形界面
