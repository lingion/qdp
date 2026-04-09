import argparse


def build_parser(
    default_quality=6,
    default_limit=20,
    default_folder="Qobuz Downloads",
    default_workers=4,
    default_prefetch_workers=None,
    default_max_retries=4,
    default_timeout=30,
    default_url_rate=8,
    default_force_proxy=False,
):
    parser = argparse.ArgumentParser(
        prog="qdp",
        description="qdp：Qobuz 极简下载器",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "urls",
        metavar="URL",
        nargs="*",
        help="Qobuz 链接（支持专辑、单曲、艺人、歌单、厂牌）",
    )

    ui_group = parser.add_argument_group("UI", "交互式 Dashboard")
    ui_group.add_argument("--ui", action="store_true", help="进入 Rich Dashboard (现代 UI)")

    search_group = parser.add_argument_group("Search Options", "交互式搜索下载")
    search_group.add_argument("-s", "--search", metavar="QUERY", help="搜索专辑（默认）")
    search_group.add_argument("-sa", "--search-album", metavar="QUERY", help="搜索专辑")
    search_group.add_argument("-st", "--search-track", metavar="QUERY", help="搜索单曲")
    search_group.add_argument("-si", "--search-artist", metavar="QUERY", help="搜索艺人（批量下载）")

    parser.add_argument("-q", "--quality", metavar="int", default=default_quality, help="画质代码: 5=MP3, 6=无损, 7=Hi-Res<96k, 27=最高")
    parser.add_argument("-o", "--directory", metavar="PATH", default=default_folder, help="下载保存目录")
    parser.add_argument("-l", "--limit", metavar="int", default=10, help="搜索结果显示数量 (默认: 10)")
    parser.add_argument("-d", "--direct", action="store_true", help="强制直连模式（忽略代理池配置）")

    parser.add_argument("--workers", metavar="int", type=int, default=default_workers, help="下载阶段并发数")
    parser.add_argument("--prefetch-workers", metavar="int", type=int, default=default_prefetch_workers, help="URL 预热(track/getFileUrl)并发数（默认跟随 --workers）")
    parser.add_argument("--max-retries", metavar="int", type=int, default=default_max_retries, help="下载阶段最大重试次数")
    parser.add_argument("--timeout", metavar="int", type=int, default=default_timeout, help="单次请求超时秒数")
    parser.add_argument("--url-rate", metavar="int", type=int, default=default_url_rate, help="track/getFileUrl 全局限速（每秒请求数）")

    # proxy strategy: prefer proxy (health sorted), fallback to direct unless forced.
    parser.add_argument("--force-proxy", dest="force_proxy", action="store_true", default=default_force_proxy, help="强制使用代理池；代理全挂时不自动直连兜底")
    parser.add_argument("--no-force-proxy", dest="force_proxy", action="store_false", help="关闭强制代理（允许失败后直连兜底）")

    parser.add_argument("-r", "--reset", action="store_true", help="重置配置文件")
    parser.add_argument("-p", "--purge", action="store_true", help="清空去重数据库")
    parser.add_argument("--no-db", action="store_true", help="忽略数据库（强制重新下载）")
    parser.add_argument("--embed-art", action="store_true", help="将封面嵌入音频文件")
    parser.add_argument("--verify", "--repair", dest="verify", action="store_true", help="校验本地专辑完整性；发现缺失时自动重置 DB 并补齐")
    parser.add_argument("--check-only", action="store_true", help="只校验，不下载、不写封面、不写 booklet、不落盘音频")
    parser.add_argument("--scan-library", action="store_true", help="扫描本地下载库并同步下载数据库")
    parser.add_argument("--doctor", action="store_true", help="检查配置、数据库、代理、下载目录与命名规则")
    parser.add_argument("--rename-library", action="store_true", help="按当前命名规则重命名本地专辑目录和音轨文件")
    parser.add_argument("--dry-run", action="store_true", help="仅预览操作，不真正写入")

    parser.add_argument("--albums-only", action="store_true", help="仅下载专辑（跳过单曲/EP）")
    parser.add_argument("--no-m3u", action="store_true", help="下载歌单时不生成 .m3u 文件")
    parser.add_argument("--no-fallback", action="store_true", help="严格画质模式（画质不满足时不降级下载）")
    parser.add_argument("--og-cover", action="store_true", help="下载原始最高分辨率封面")
    parser.add_argument("--no-cover", action="store_true", help="不下载封面")
    parser.add_argument("-ff", "--folder-format", metavar="FMT", help="自定义文件夹命名格式")
    parser.add_argument("-tf", "--track-format", metavar="FMT", help="自定义文件名命名格式")
    parser.add_argument("-s-disc", "--smart-discography", action="store_true", help="智能筛选（下载艺人时过滤重复/杂乱专辑）")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出更详细的人话日志")
    parser.add_argument("--debug", action="store_true", help="输出调试级别技术细节")

    return parser
