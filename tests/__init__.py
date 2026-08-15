# -*- coding: utf-8 -*-
"""音乐感知 / 更新检查功能的测试包。

运行（在仓库根目录）：
    python -m unittest discover -s tests -t .
"""

import logging

# 被测代码在「清单格式非法」「写文件失败」等降级路径上会主动记日志，
# 这是正确行为。但测试里这些日志会淹没真正的失败信息，所以统一静音。
# 需要断言日志内容时，用 assertLogs 局部打开即可。
logging.disable(logging.CRITICAL)
