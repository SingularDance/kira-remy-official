# -*- coding: utf-8 -*-
"""程序版本号。

单独成文件而不是塞进 config.py，理由：

1. **打包脚本可以直接重写它**。pack.bat 发版时改这一个文件即可，
   不用去正则替换 config.py 里的某一行，出错概率低得多。
2. **零依赖**。任何模块（包括 updater）都能安全 import，不会引入
   config.py 那一堆全局状态和文件读写。

发版流程：改这里 → 打包 → 在 GitHub 上建同名 tag 的 release。
三者必须一致，否则用户会被反复提示更新一个已经装上的版本。

版本号规则：三段式 `主.次.修订`。updater 用整数元组比较，
所以不要用日期（20260813）或带字母的写法。
"""

VERSION = "1.1.1"

# 发布渠道。代码托管在 Gitee（Fizz/ReiPer），但发布包挂在 GitHub Releases，
# 二者不是同一个地方——更新检查读的是下面这个仓库。
GITHUB_OWNER = "SingularDance"
GITHUB_REPO = "kira-remy-official"
