import argparse

def qobuz_dl_args(
    default_quality=6, default_limit=20, default_folder="Qobuz Downloads"
):
    parser = argparse.ArgumentParser(
        prog="qd",
        description="Qobuz 极简下载器 (Proxy版)",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # 核心参数：URL (位置参数)
    parser.add_argument(
        "urls",
        metavar="URL",
        nargs="*", 
        help="Qobuz 链接 (支持专辑, 单曲, 艺人, 歌单)",
    )

    # --- 搜索参数 ---
    search_group = parser.add_argument_group('Search Options', '交互式搜索下载')
    search_group.add_argument("-s", "--search", metavar="QUERY", help="搜索专辑 (默认)")
    search_group.add_argument("-sa", "--search-album", metavar="QUERY", help="搜索专辑")
    search_group.add_argument("-st", "--search-track", metavar="QUERY", help="搜索单曲")
    search_group.add_argument("-si", "--search-artist", metavar="QUERY", help="搜索艺人 (批量下载)")
    
    # 常用配置
    parser.add_argument(
        "-q", "--quality",
        metavar="int",
        default=default_quality,
        help="画质代码: 5=MP3, 6=无损, 7=Hi-Res<96k, 27=最高 (默认: 27)"
    )
    parser.add_argument(
        "-o", "--directory",
        metavar="PATH",
        default=default_folder,
        help=f"下载保存目录"
    )
    parser.add_argument(
        "-l", "--limit",
        metavar="int",
        default=10,
        help="搜索结果显示数量 (默认: 10)"
    )

    # --- 直连参数 ---
    parser.add_argument(
        "-d", "--direct", 
        action="store_true", 
        help="强制直连模式 (忽略代理池配置)"
    )

    # 功能开关
    parser.add_argument("-r", "--reset", action="store_true", help="重置配置文件")
    parser.add_argument("-p", "--purge", action="store_true", help="清空去重数据库")
    parser.add_argument("--no-db", action="store_true", help="忽略数据库 (强制重新下载)")
    parser.add_argument("--embed-art", action="store_true", help="将封面嵌入音频文件")
    
    # 高级参数
    parser.add_argument("--albums-only", action="store_true", help="仅下载专辑 (跳过单曲/EP)")
    parser.add_argument("--no-m3u", action="store_true", help="下载歌单时不生成 .m3u 文件")
    parser.add_argument("--no-fallback", action="store_true", help="严格画质模式 (画质不满足时不降级下载)")
    parser.add_argument("--og-cover", action="store_true", help="下载原始最高分辨率封面")
    parser.add_argument("--no-cover", action="store_true", help="不下载封面")
    parser.add_argument("-ff", "--folder-format", metavar="FMT", help="自定义文件夹命名格式")
    parser.add_argument("-tf", "--track-format", metavar="FMT", help="自定义文件名命名格式")
    parser.add_argument("-s-disc", "--smart-discography", action="store_true", help="智能筛选 (下载艺人时过滤重复/杂乱专辑)")

    return parser