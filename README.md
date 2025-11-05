# Copymanga Downloader
基于 Copymanga API & Aria2c RPC 的控制台漫画下载工具
```
Active code page: 65001

┏━━━━━━ 漫画列表
┃ 00. [ 1 |  | 1 ] 
┃ 01. [ 2 |  | 2 ] 
┃ 02. [ 3 |  | 3 ] 
┃ 03. [ 4 |  | 4 ] 
┃ 04. [ 5 |  | 5 ] 
┃ 05. [ 6 |  | 6 ] 
┃ 06. [ 7 |  | 7 ] 
┃ 07. [ 8 |  | 8 ] 
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┏━━━━━━ 所有命令
┃ help                                      显示命令列表
┃ update [index/all]                        更新数据库
┃ download [index/all]                      下载文件
┃ scan [index/all]                          标记存在的文件到已下载
┃ check [index/all]                         检查本地文件
┃ pack-info [index/all]                     显示漫画打包信息
┃ pack-update [num] [start] [index/all]     更新漫画打包信息 num=打包分割章节号 start=起始章节号
┃ pack-run [index/all]                      打包漫画
┃ show [index]                              显示详细信息
┃ mark [index]                              标记已下载但不存在的文件
┃ delete [index]                            删除数据库
┃ search [keyword]                          使用关键词搜索并创建数据库
┃ init [pathword]                           使用路径词创建数据库
┃ list                                      显示漫画列表
┃ clear                                     清除控制台历史输出
┃ exit                                      退出 或 双击Ctrl+C
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

> 
```

## 使用说明
下载实现依赖 aria2c 需要在环境变量内可用

脚本工作后会生成数据目录  
 - db.nosync 漫画元数据与文件数据库
 - dl.nosync 漫画本地文件下载根目录
 - 例 db.nosync\漫画路径词.db 本地数据库/切勿修改
 - 例 db.nosync\漫画路径词.ini 打包CBZ配置/如需自定义打包章节需要手动编辑
 - 例 dl.nosync\漫画名称\分组名称\排序索引.章节名-页号.webp

## 脚本依赖
 - python -m pip install sqlalchemy spdlog requests  
 - spdlog 需要本地编译 (windows要求安装msvc)

## 当前支持的功能
 - 见上方命令行示例
 - 下载和请求遵循API次数限制
 - 自动使用系统网络代理

## 设计中功能
 - 更新章节同时下载的多线程模式
 - 额外的图形界面
