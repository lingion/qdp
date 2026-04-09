from colorama import Style, Fore, init

init(autoreset=True)

# 移除 BRIGHT，使用默认亮度，减少刺眼感
DF = Style.NORMAL
BG = Style.NORMAL 
RESET = Style.RESET_ALL
OFF = Style.DIM

# 使用 Colorama 的标准色，但在 rich 组件中我们会覆盖它们
RED = Fore.RED
BLUE = Fore.BLUE
GREEN = Fore.GREEN
YELLOW = Fore.YELLOW
CYAN = Fore.CYAN
MAGENTA = Fore.MAGENTA