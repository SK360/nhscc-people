#!/usr/bin/env python3
"""
NHSCC Results Scraper
Scrapes event results from nhscc.com/results.php and builds a SQLite database.

Requirements:
    pip install requests beautifulsoup4 playwright
    playwright install chromium

Usage:
    python nhscc_scraper.py
    python nhscc_scraper.py --year 2024          # scrape a single year
    python nhscc_scraper.py --start-year 2020    # scrape from 2020 onward
    python nhscc_scraper.py --output results.db  # custom output path
    python nhscc_scraper.py --csv                # also export CSV alongside SQLite
"""

import argparse
import csv
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DriverResult:
    event_date: str        # ISO date string e.g. "2024-04-14"
    event_year: int
    car_class: str
    car_number: str
    name: str
    car: str
    best_time: Optional[float]
    pax_index: Optional[float]
    pax_time: Optional[float]
    source_url: str
    scrape_method: str     # "static_html" or "playwright"

# ---------------------------------------------------------------------------
# All event URLs parsed from results.php
# ---------------------------------------------------------------------------

EVENT_URLS = [
    # 2026
    ("2026", "2026-03-29", "https://nhscc.com/2026/2026-03-29/"),
    ("2026", "2026-04-12", "https://nhscc.com/2026/2026-04-12/"),
    ("2026", "2026-04-26", "https://nhscc.com/2026/2026-04-26/"),
    ("2026", "2026-05-03", "https://nhscc.com/2026/2026-05-03/"),
    # 2025
    ("2025", "2025-04-13", "https://nhscc.com/2025/2025-04-13/"),
    ("2025", "2025-04-27", "https://nhscc.com/2025/2025-04-27/"),
    ("2025", "2025-05-04", "https://nhscc.com/2025/2025-05-04/"),
    ("2025", "2025-05-18", "https://nhscc.com/2025/2025-05-18/"),
    ("2025", "2025-PVGP-1", "https://nhscc.com/2025/PVGP/PVGP-2025-group-1/"),
    ("2025", "2025-PVGP-2", "https://nhscc.com/2025/PVGP/PVGP-2025-group-2/"),
    ("2025", "2025-PVGP-3", "https://nhscc.com/2025/PVGP/PVGP-2025-group-3/"),
    ("2025", "2025-PVGP-4", "https://nhscc.com/2025/PVGP/PVGP-2025-group-4/"),
    ("2025", "2025-09-07", "https://nhscc.com/2025/2025-09-07/"),
    ("2025", "2025-09-28", "https://nhscc.com/2025/2025-09-28/"),
    ("2025", "2025-10-05", "https://nhscc.com/2025/2025-10-05/"),
    ("2025", "2025-10-12", "https://nhscc.com/2025/2025-10-12/"),
    ("2025", "2025-11-02", "https://nhscc.com/2025/2025-11-02/"),
    # 2024
    ("2024", "2024-04-14", "https://nhscc.com/2024/2024-04-14/"),
    ("2024", "2024-04-28", "https://nhscc.com/2024/2024-04-28/"),
    ("2024", "2024-05-05", "https://nhscc.com/2024/2024-05-05/"),
    ("2024", "2024-05-19", "https://nhscc.com/2024/2024-05-19/"),
    ("2024", "2024-09-08", "https://nhscc.com/2024/2024-09-08/"),
    ("2024", "2024-09-22", "https://nhscc.com/2024/2024-09-22/"),
    ("2024", "2024-09-29", "https://nhscc.com/2024/2024-09-29/"),
    ("2024", "2024-10-06", "https://nhscc.com/2024/2024-10-06/"),
    ("2024", "2024-10-13", "https://nhscc.com/2024/2024-10-13/"),
    # 2023
    ("2023", "2023-04-23", "https://nhscc.com/2023/2023-04-23/"),
    ("2023", "2023-04-30", "https://nhscc.com/2023/2023-04-30/"),
    ("2023", "2023-05-07", "https://nhscc.com/2023/2023-05-07/"),
    ("2023", "2023-05-21", "https://nhscc.com/2023/2023-05-21/"),
    ("2023", "2023-09-10", "https://nhscc.com/2023/2023-09-10/"),
    ("2023", "2023-09-17", "https://nhscc.com/2023/2023-09-17/"),
    ("2023", "2023-10-01", "https://nhscc.com/2023/2023-10-01/"),
    ("2023", "2023-10-08", "https://nhscc.com/2023/2023-10-08/"),
    ("2023", "2023-10-15", "https://nhscc.com/2023/2023-10-15/"),
    # 2022
    ("2022", "2022-04-10", "http://nhscc.com/2022/2022-4-10_Revised1/index.htm"),
    ("2022", "2022-05-01", "http://nhscc.com/2022/2022-5-1/index.htm"),
    ("2022", "2022-05-15", "http://nhscc.com/2022/2022-5-15/index.htm"),
    ("2022", "2022-05-22", "http://nhscc.com/2022/2022-5-22/index.htm"),
    ("2022", "2022-09-11", "http://nhscc.com/2022/2022-9-11/index.htm"),
    ("2022", "2022-09-25", "http://nhscc.com/2022/2022-9-25/index.htm"),
    ("2022", "2022-10-02", "http://nhscc.com/2022/2022-10-2/index.htm"),
    ("2022", "2022-10-09", "http://nhscc.com/2022/2022-10-9/index.htm"),
    ("2022", "2022-10-16", "http://nhscc.com/2022/2022-10-16/index.htm"),
    # 2021
    ("2021", "2021-04-11", "http://nhscc.com/2021/20210411/index.htm"),
    ("2021", "2021-04-18", "http://nhscc.com/2021/2021-4-18/index.htm"),
    ("2021", "2021-04-25", "http://nhscc.com/2021/2021-4-25/index.htm"),
    ("2021", "2021-05-02", "http://nhscc.com/2021/2021-5-2/index.htm"),
    ("2021", "2021-05-16", "http://nhscc.com/2021/2021-5-16/index.htm"),
    ("2021", "2021-05-23", "http://nhscc.com/2021/2021-5-23/index.htm"),
    ("2021", "2021-09-12", "http://nhscc.com/2021/2021-9-12/index.htm"),
    ("2021", "2021-09-26", "http://nhscc.com/2021/2021-9-26/index.htm"),
    ("2021", "2021-10-03", "http://nhscc.com/2021/2021-10-3/index.htm"),
    ("2021", "2021-10-17", "http://nhscc.com/2021/2021-10-17/index.htm"),
    ("2021", "2021-10-24", "http://nhscc.com/2021/2021-10-24a/index.htm"),
    # 2020
    ("2020", "2020-06-28", "http://nhscc.com/2020/20200628/index.htm"),
    ("2020", "2020-07-19", "http://nhscc.com/2020/2020-7-26/index.htm"),
    ("2020", "2020-08-09", "http://nhscc.com/2020/2020-8-09/index.htm"),
    ("2020", "2020-08-23", "http://nhscc.com/2020/2020-8-23/index.htm"),
    ("2020", "2020-08-30", "http://nhscc.com/2020/2020-8-30/index.htm"),
    ("2020", "2020-09-13", "http://nhscc.com/2020/2020-9-13/index.htm"),
    ("2020", "2020-09-27", "http://nhscc.com/2020/2020-9-27/index.htm"),
    ("2020", "2020-10-04", "http://nhscc.com/2020/2020-10-04/index.htm"),
    ("2020", "2020-10-11", "http://nhscc.com/2020/2020-10-11/index.htm"),
    ("2020", "2020-10-18", "http://nhscc.com/2020/2020-10-18/index.htm"),
    # 2019
    ("2019", "2019-04-07", "http://nhscc.com/2019/2019-4-7/index.htm"),
    ("2019", "2019-04-14", "http://nhscc.com/2019/2019-4-14/index.htm"),
    ("2019", "2019-04-28", "http://nhscc.com/2019/2019-4-28/index.htm"),
    ("2019", "2019-05-05", "http://nhscc.com/2019/2019-5-5/index.htm"),
    ("2019", "2019-05-19", "http://nhscc.com/2019/2019-5-19/index.htm"),
    ("2019", "2019-09-08", "http://nhscc.com/2019/2109-9-8/index.htm"),
    ("2019", "2019-09-22", "http://nhscc.com/2019/2019-9-22/index.htm"),
    ("2019", "2019-09-29", "http://nhscc.com/2019/2019-9-29/index.htm"),
    ("2019", "2019-10-06", "http://nhscc.com/2019/2019-10-6/index.htm"),
    ("2019", "2019-10-13", "http://nhscc.com/2019/2019-10-13/index.htm"),
    ("2019", "2019-10-20a", "http://nhscc.com/2019/2019-10-20/index.htm"),
    ("2019", "2019-10-20b", "http://nhscc.com/2019/2019-10-20/short-course/index.htm"),
    # 2018
    ("2018", "2018-04-08", "http://nhscc.com/2018/20180408/2018-4-8/index.htm"),
    ("2018", "2018-04-22", "http://nhscc.com/2018/20180422/2018-4-22/index.htm"),
    ("2018", "2018-05-06", "http://nhscc.com/2018/20180506/2018-5-6/index.htm"),
    ("2018", "2018-05-20", "http://nhscc.com/2018/20180520/2018-5-20/index.htm"),
    ("2018", "2018-09-30", "http://nhscc.com/2018/20180930/2018-9-30/index.htm"),
    ("2018", "2018-10-14", "http://nhscc.com/2018/20181014/2018-10-14/index.htm"),
    ("2018", "2018-10-21", "http://nhscc.com/2018/20181021/2018-10-21_Rev2/index.htm"),
    ("2018", "2018-10-28", "http://nhscc.com/2018/20181028/2018-10-28/index.htm"),
    # 2017
    ("2017", "2017-04-02", "http://nhscc.com/2017/20170402/2017-4-2/index.htm"),
    ("2017", "2017-04-09", "http://nhscc.com/2017/20170409/2017-4-9/index.htm"),
    ("2017", "2017-04-23", "http://nhscc.com/2017/20170423/2017-4-23/index.htm"),
    ("2017", "2017-05-07", "http://nhscc.com/2017/20170507/2017-5-7/index.htm"),
    ("2017", "2017-05-21", "http://nhscc.com/2017/20170521/2017-5-21/index.htm"),
    ("2017", "2017-09-03", "http://nhscc.com/2017/20170903/index.htm"),
    ("2017", "2017-10-08", "http://nhscc.com/2017/20171008/2017-10-8/index.htm"),
    ("2017", "2017-10-22", "http://nhscc.com/2017/20171022/2017-10-22/index.htm"),
    ("2017", "2017-10-29", "http://nhscc.com/2017/20171029/2017-10-29/index.htm"),
    # 2016
    ("2016", "2016-04-10", "http://nhscc.com/2016/2016-04-10/4-10-2016/index.htm"),
    ("2016", "2016-04-24", "http://nhscc.com/2016/2016-04-24/4-24-2016/index.htm"),
    ("2016", "2016-05-01", "http://nhscc.com/2016/2016-05-01/5-1-2016/index.htm"),
    ("2016", "2016-05-29", "http://nhscc.com/2016/2016-05-29/5-29-2016/index.htm"),
    ("2016", "2016-09-04", "http://nhscc.com/2016/2016-09-04/8-4-2016/index.htm"),
    ("2016", "2016-09-25", "http://nhscc.com/2016/9-25-2016/index.htm"),
    ("2016", "2016-10-02", "http://nhscc.com/2016/10-2-2016/index.htm"),
    ("2016", "2016-10-09", "http://nhscc.com/2016/2016-10-9/index.htm"),
    # 2015
    ("2015", "2015-04-12", "http://nhscc.com/2015/2015-04-12/4-12-2015/index.htm"),
    ("2015", "2015-04-26", "http://nhscc.com/2015/2015-04-26/4-26-2015/index.htm"),
    ("2015", "2015-05-03", "http://nhscc.com/2015/2015-05-03/5-3-2105/index.htm"),
    ("2015", "2015-05-24", "http://nhscc.com/2015/2015-05-24/5-24-2015/index.htm"),
    ("2015", "2015-09-13", "http://nhscc.com/2015/2015-09-13/9-13-2015/index.htm"),
    ("2015", "2015-09-27", "http://nhscc.com/2015/2015-09-27/9-27-2015/index.htm"),
    ("2015", "2015-10-04", "http://nhscc.com/2015/2015-10-04/10-4-2015/index.htm"),
    ("2015", "2015-10-18", "http://nhscc.com/2015/2015-10-18/10-18-2015/index.htm"),
    # 2014
    ("2014", "2014-04-13", "http://nhscc.com/2014/20140413/4-13-2014/index.htm"),
    ("2014", "2014-04-27", "http://nhscc.com/2014/20140427/4-27-2014/index.htm"),
    ("2014", "2014-05-25", "http://nhscc.com/2014/20140525/5-26-2014/index.htm"),
    ("2014", "2014-09-28", "http://nhscc.com/2014/20140928/9-28-2014/index.htm"),
    ("2014", "2014-10-05", "http://nhscc.com/2014/20141005/10-5-2014/index.htm"),
    ("2014", "2014-10-19", "http://nhscc.com/2014/20141019/10-19-2104/index.htm"),
    ("2014", "2014-10-26", "http://nhscc.com/2014/20141026/10-26-2014/index.htm"),
    # 2013
    ("2013", "2013-04-14", "http://nhscc.com/2013/20130414/4-14-2013/index.htm"),
    ("2013", "2013-04-28", "http://nhscc.com/2013/20130428/4-28-2013/index.htm"),
    ("2013", "2013-05-12", "http://nhscc.com/2013/20130512/5-12-2013/index.htm"),
    ("2013", "2013-05-26", "http://nhscc.com/2013/20130526/5-26-2013/index.htm"),
    ("2013", "2013-09-08", "http://nhscc.com/2013/20130908/9-8-2013/index.htm"),
    ("2013", "2013-09-22", "http://nhscc.com/2013/20130922/9-22-2013/index.htm"),
    ("2013", "2013-10-06", "http://nhscc.com/2013/20131006/10-6-2013/index.htm"),
    ("2013", "2013-10-20", "http://nhscc.com/2013/20131020/10-20-2013/index.htm"),
    # 2012
    ("2012", "2012-04-15", "http://nhscc.com/2012/20120415/4-15-2012/index.htm"),
    ("2012", "2012-04-22", "http://nhscc.com/2012/20120422/4-22-2012/index.htm"),
    ("2012", "2012-05-13", "http://nhscc.com/2012/20120513/5-13-2012/index.htm"),
    ("2012", "2012-05-27", "http://nhscc.com/2012/20120527/5-26-2012/index.htm"),
    ("2012", "2012-09-09", "http://nhscc.com/2012/20120909/9-9-2012/index.htm"),
    ("2012", "2012-09-23", "http://nhscc.com/2012/20120923/9-23-2012/index.htm"),
    ("2012", "2012-10-07", "http://nhscc.com/2012/20121007/10-7-2012/index.htm"),
    ("2012", "2012-10-21", "http://nhscc.com/2012/20121021/10-21-2012/index.htm"),
    ("2012", "2012-10-28", "http://nhscc.com/2012/20121028/10-28-2012/index.htm"),
    # 2011
    ("2011", "2011-04-03", "http://nhscc.com/2011/20110403/4-3-2011/index.htm"),
    ("2011", "2011-04-10", "http://nhscc.com/2011/20110410/4-10-2011/index.htm"),
    ("2011", "2011-05-01", "http://nhscc.com/2011/20110501/5-1-2011/index.htm"),
    ("2011", "2011-05-15", "http://nhscc.com/2011/20110515/5-15-2011/index.htm"),
    ("2011", "2011-05-22", "http://nhscc.com/2011/20110522/5-22-2011/index.htm"),
    ("2011", "2011-09-11", "http://nhscc.com/2011/20110911/9-11-11/index.htm"),
    ("2011", "2011-10-02", "http://nhscc.com/2011/20111002/10-2-2011/index.htm"),
    ("2011", "2011-10-03", "http://nhscc.com/2010/oct-3-2010/index.htm"),
    ("2011", "2011-10-16", "http://nhscc.com/2011/20111016/10-16-2011/index.htm"),
    ("2011", "2011-10-23", "http://nhscc.com/2011/20111023/10-23-2011/index.htm"),
    # 2010
    ("2010", "2010-04-11", "http://nhscc.com/2010/20100411/april112010/index.htm"),
    ("2010", "2010-04-18", "http://nhscc.com/2010/20100418/april182010/index.htm"),
    ("2010", "2010-04-25", "http://nhscc.com/2010/20100425/april252010/index.htm"),
    ("2010", "2010-05-23", "http://nhscc.com/2010/20100523/may232010/index.htm"),
    ("2010", "2010-09-19", "http://nhscc.com/2010/20100919/sept-19-2010/index.htm"),
    ("2010", "2010-09-26", "http://nhscc.com/2010/20100926/sept-26-2010/index.htm"),
    ("2010", "2010-10-17", "http://nhscc.com/2010/20101017/oct-17-2010/index.htm"),
    # 2009
    ("2009", "2009-04-05", "http://nhscc.com/2009/20090405/April52009/index.htm"),
    ("2009", "2009-04-19", "http://nhscc.com/2009/20090419/April_19_2009/index.htm"),
    ("2009", "2009-04-26", "http://nhscc.com/2009/20090426/April262009/index.htm"),
    ("2009", "2009-05-17", "http://nhscc.com/2009/20090517/May_17_2009/May_17_2009/index.htm"),
    ("2009", "2009-09-13", "http://nhscc.com/2009/20090913/Sept132009/index.htm"),
    ("2009", "2009-09-20", "http://nhscc.com/2009/20090920/Sept_20_2009/index.htm"),
    ("2009", "2009-09-27", "http://nhscc.com/2009/20090927/Sept_27_2009/index.htm"),
    ("2009", "2009-10-04", "http://nhscc.com/2009/20091004/Oct42009/index.htm"),
    ("2009", "2009-10-18", "http://nhscc.com/2009/20091018/Oct_18_2009/index.htm"),
    # 2008
    ("2008", "2008-04-06", "http://nhscc.com/2008/20080406/April062008.htm"),
    ("2008", "2008-04-20", "http://nhscc.com/2008/20080420/nh/20080420.htm"),
    ("2008", "2008-05-04", "http://nhscc.com/2008/20080504/2008.5.4/2008.5.4.htm"),
    ("2008", "2008-05-18", "http://nhscc.com/2008/20080518/2008.5.18a1a/2008.5.18a.htm"),
    ("2008", "2008-09-07", "http://nhscc.com/2008/20080907/Sept_7_2008.htm"),
    ("2008", "2008-09-21", "http://nhscc.com/2008/20080921/Sept_21_2008.htm"),
    ("2008", "2008-09-28", "http://nhscc.com/2008/20080928/Sept_28_2008.htm"),
    ("2008", "2008-10-05", "http://nhscc.com/2008/20081005/Autumn_Leaf_29.htm"),
    ("2008", "2008-11-02", "http://nhscc.com/2008/20081102/Nov_2_2008.htm"),
    # 2007
    ("2007", "2007-04-15", "http://nhscc.com/2007/20070415/20070415.htm"),
    ("2007", "2007-04-22", "http://nhscc.com/2007/20070422/20070422/20070422.htm"),
    ("2007", "2007-05-06", "http://nhscc.com/2007/20070506/20070506.htm"),
    ("2007", "2007-05-20", "http://nhscc.com/2007/20070520/20070520.htm"),
    ("2007", "2007-06-30", "http://nhscc.com/2007/20070630/June_30_2007.htm"),
    ("2007", "2007-09-08", "http://nhscc.com/2007/20070908/Sept_8_2007/Sept_8_2007.htm"),
    ("2007", "2007-09-23", "http://nhscc.com/2007/20070923/Sept_23_2007.htm"),
    ("2007", "2007-10-07", "http://nhscc.com/2007/20071007/Oct_7_2007.htm"),
    ("2007", "2007-11-11", "http://nhscc.com/2007/20071111/11_11_2007/Nov_11_2007.htm"),
    # 2006
    ("2006", "2006-04-09", "http://nhscc.com/2006/20060409/20060409.htm"),
    ("2006", "2006-04-23", "http://nhscc.com/2006/20060423/20060423.htm"),
    ("2006", "2006-05-07", "http://nhscc.com/2006/20060507/20060507.htm"),
    ("2006", "2006-05-21", "http://nhscc.com/2006/20060521/20060521.htm"),
    ("2006", "2006-08-27", "http://nhscc.com/2006/20060827/20060827/20060827.htm"),
    ("2006", "2006-09-10", "http://nhscc.com/2006/20060910/20060910.htm"),
    ("2006", "2006-09-17", "http://nhscc.com/2006/20060917/20060917.htm"),
    ("2006", "2006-09-24", "http://nhscc.com/2006/20060924/Sept_26_2006.htm"),
    ("2006", "2006-10-01", "http://nhscc.com/2006/20061001/20061001.htm"),
    ("2006", "2006-10-22", "http://nhscc.com/2006/20061022/20061022.htm"),
    # 2005
    ("2005", "2005-04-10", "http://nhscc.com/2005/20050410/HTML_Export.htm"),
    ("2005", "2005-04-17", "http://nhscc.com/2005/20050417/HTML_Export.htm"),
    ("2005", "2005-05-15", "http://nhscc.com/2005/20050515/HTML_Export5.15.htm"),
    ("2005", "2005-05-22", "http://nhscc.com/2005/20050522/HTML_Export.htm"),
    ("2005", "2005-06-26", "http://nhscc.com/2005/20050626/HTML_Export.htm"),
    ("2005", "2005-09-11", "http://nhscc.com/2005/20050911/HTML_Export1_RF/HTML_Export1.htm"),
    ("2005", "2005-09-18", "http://nhscc.com/2005/20050918/HTML_Export.htm"),
    ("2005", "2005-10-02", "http://nhscc.com/2005/20051002/HTML_Export.htm"),
    ("2005", "2005-10-09", "http://nhscc.com/2005/20051009/HTML_Export.htm"),
    # 2004
    ("2004", "2004-04-04", "http://nhscc.com/2004/040404.htm"),
    ("2004", "2004-04-18", "http://nhscc.com/2004/040418.htm"),
    ("2004", "2004-05-02", "http://nhscc.com/2004/040502.htm"),
    ("2004", "2004-05-16", "http://nhscc.com/2004/040516.htm"),
    ("2004", "2004-05-23", "http://nhscc.com/2004/040523.htm"),
    ("2004", "2004-06-13", "http://nhscc.com/2004/040613.htm"),
    ("2004", "2004-09-12", "http://nhscc.com/2004/040912.htm"),
    ("2004", "2004-09-26", "http://nhscc.com/2004/040926.htm"),
    ("2004", "2004-10-03", "http://nhscc.com/2004/041003.htm"),
    ("2004", "2004-10-17", "http://nhscc.com/2004/041017.htm"),
    # 2003
    ("2003", "2003-04-06", "http://nhscc.com/2003/030406.htm"),
    ("2003", "2003-04-27", "http://nhscc.com/2003/030427.htm"),
    ("2003", "2003-05-04", "http://nhscc.com/2003/030504.htm"),
    ("2003", "2003-05-18", "http://nhscc.com/2003/030518.htm"),
    ("2003", "2003-07-01", "http://nhscc.com/2003/030701.htm"),
    ("2003", "2003-07-06", "http://nhscc.com/2003/030706.htm"),
    ("2003", "2003-09-01", "http://nhscc.com/2003/030901.htm"),
    ("2003", "2003-09-07", "http://nhscc.com/2003/030907.htm"),
    ("2003", "2003-09-14", "http://nhscc.com/2003/030914.htm"),
    ("2003", "2003-09-28", "http://nhscc.com/2003/030928.htm"),
    ("2003", "2003-10-05", "http://nhscc.com/2003/031005.htm"),
    ("2003", "2003-10-19", "http://nhscc.com/2003/031019.htm"),
    # 2002
    ("2002", "2002-04-07", "http://nhscc.com/2002/020407.htm"),
    ("2002", "2002-04-21", "http://nhscc.com/2002/020421.htm"),
    ("2002", "2002-05-05", "http://nhscc.com/2002/020505.htm"),
    ("2002", "2002-05-19", "http://nhscc.com/2002/020519.htm"),
    ("2002", "2002-09-08", "http://nhscc.com/2002/020908.txt"),
    ("2002", "2002-09-15", "http://nhscc.com/2002/020915.htm"),
    ("2002", "2002-09-29", "http://nhscc.com/2002/020929.htm"),
    ("2002", "2002-10-06", "http://nhscc.com/2002/021006.htm"),
    ("2002", "2002-10-20", "http://nhscc.com/2002/021020.htm"),
    # 2001
    ("2001", "2001-04-01", "http://nhscc.com/2001/010401.htm"),
    ("2001", "2001-04-22", "http://nhscc.com/2001/010422.htm"),
    ("2001", "2001-05-06", "http://nhscc.com/2001/010506.htm"),
    ("2001", "2001-05-20", "http://nhscc.com/2001/010520.htm"),
    ("2001", "2001-09-09", "http://nhscc.com/2001/010909.htm"),
    ("2001", "2001-09-16", "http://nhscc.com/2001/010916.htm"),
    ("2001", "2001-10-07", "http://nhscc.com/2001/011007.htm"),
    ("2001", "2001-10-14", "http://nhscc.com/2001/011014.htm"),
    ("2001", "2001-10-21", "http://nhscc.com/2001/011021.htm"),
    ("2001", "2001-10-28", "http://nhscc.com/2001/011028.htm"),
    # 2000
    ("2000", "2000-04-09", "http://nhscc.com/2000/000409.htm"),
    ("2000", "2000-04-30", "http://nhscc.com/2000/000430.htm"),
    ("2000", "2000-05-07", "http://nhscc.com/2000/000507.htm"),
    ("2000", "2000-05-21", "http://nhscc.com/2000/000521.htm"),
    ("2000", "2000-09-10", "http://nhscc.com/2000/000910.htm"),
    ("2000", "2000-10-08", "http://nhscc.com/2000/001008.htm"),
    ("2000", "2000-10-15", "http://nhscc.com/2000/001015.htm"),
    ("2000", "2000-10-22", "http://nhscc.com/2000/001022.htm"),
    ("2000", "2000-11-05", "http://nhscc.com/2000/001105.htm"),
]

# ---------------------------------------------------------------------------
# Static HTML parser (pre-2008 era, plain HTML tables)
# ---------------------------------------------------------------------------

def safe_float(val: str) -> Optional[float]:
    """Convert string to float, return None if invalid or 999."""
    try:
        f = float(val.strip())
        return None if f >= 999 else f
    except (ValueError, AttributeError):
        return None


def parse_pre_format(pre_text: str, url: str, year: str, date_str: str) -> list[DriverResult]:
    """
    Parse the fixed-width <pre> text format used by some 2002-2003 pages.
    Header: Class Car#    Driver             Car        Run 1   P1 ... Best   Place PAX
    """
    lines = pre_text.split('\n')
    results = []

    # Find the header line — accepts both "Driver" and "Name" column labels
    header = None
    header_idx = None
    for i, line in enumerate(lines):
        if all(tok in line for tok in ('Class', 'Car#', 'Best', 'PAX')):
            if 'Driver' in line or 'Name' in line:
                header = line
                header_idx = i
                break

    if header is None:
        return []

    # Derive column start positions from the header
    try:
        col_class   = header.index('Class')
        col_carnum  = header.index('Car#')
        col_driver  = header.index('Driver') if 'Driver' in header else header.index('Name')
        col_carname = header.index('Car', col_driver)   # skip "Car#" earlier in the line
        col_runs    = header.index('Run')               # start of run-time columns
        col_best    = header.index('Best')
        col_place   = header.index('Place')
        col_pax     = header.index('PAX')
    except ValueError:
        return []

    for line in lines[header_idx + 1:]:
        if not line.strip() or len(line) < col_best:
            continue

        class_val  = line[col_class:col_carnum].strip()
        car_raw    = line[col_carnum:col_driver].strip()
        driver_val = line[col_driver:col_carname].strip()
        car_val    = line[col_carname:col_runs].strip()
        best_val   = line[col_best:col_place].strip() if len(line) > col_best else ''
        pax_val    = line[col_pax:].strip() if len(line) > col_pax else ''

        # Must be a real class (letters only) and have a driver name
        if not class_val or not driver_val or not re.match(r'^[A-Z]+$', class_val):
            continue

        # Car number is the leading digits in the Car# cell
        num_match = re.match(r'^(\d+)', car_raw)
        if not num_match:
            continue
        car_number = num_match.group(1)

        results.append(DriverResult(
            event_date=date_str,
            event_year=int(year),
            car_class=class_val,
            car_number=car_number,
            name=driver_val,
            car=car_val,
            best_time=safe_float(best_val),
            pax_index=None,
            pax_time=safe_float(pax_val),
            source_url=url,
            scrape_method="static_html",
        ))

    return results


def parse_static_html(html: str, url: str, year: str, date_str: str) -> list[DriverResult]:
    """
    Parse old-style Finish-Time static HTML tables.

    Three known formats:
      pre-text:        Fixed-width <pre> block (some 2002-2003 pages)
      2004+ (CarID):   Bump | CarID | Name | Car | R1..R6+penalties | Best | PAX Index | PAX Time
      2003-era (Car#): Class | Car# | Name | Car | R1..R5+penalties | Best | Place | PAX
    """
    soup = BeautifulSoup(html, "html.parser")

    # Fixed-width <pre> format takes priority when present
    pre_tag = soup.find('pre')
    if pre_tag:
        return parse_pre_format(pre_tag.get_text(), url, year, date_str)
    results = []

    def _find_col(lower_cells, *names):
        """Return the index of the first matching column name (case-insensitive), or None."""
        for n in names:
            if n in lower_cells:
                return lower_cells.index(n)
        return None

    rows = soup.find_all("tr")

    # Scan for a header row, then parse data rows using column-index mapping.
    # This handles the many table-layout variations seen across 2002-2004 pages.
    col_map = None
    for row in rows:
        cells_raw = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        cells_low = [c.lower().strip() for c in cells_raw]

        if col_map is None:
            # Detect header row: must have a recognisable name-like and class-like column
            has_name = any(c in cells_low for c in ("name", "driver", "fname"))
            has_class = any(c in cells_low for c in ("class", "bump"))
            if not (has_name and has_class):
                continue

            # Build column map from header
            col_map = {
                "name":      _find_col(cells_low, "name", "driver"),
                "fname":     _find_col(cells_low, "fname"),
                "lname":     _find_col(cells_low, "lname"),
                "class":     _find_col(cells_low, "class", "bump"),
                "car_num":   _find_col(cells_low, "car#", "car #", "carid"),
                "car":       _find_col(cells_low, "car"),
                "make":      _find_col(cells_low, "make"),
                "model":     _find_col(cells_low, "model"),
                "best":      _find_col(cells_low, "best", "best time", "best run"),
                "pax":       _find_col(cells_low, "pax", "pax time"),
                "pax_index": _find_col(cells_low, "pax index", "index"),
                # Track whether col 0 in the header was blank (unlabeled competition-class column)
                "_col0_blank": cells_raw[0].strip() == "" if cells_raw else False,
            }
            continue  # header row consumed

        # Data row
        n = len(cells_raw)

        def _cell(idx):
            return cells_raw[idx].strip() if idx is not None and idx < n else ""

        # Build driver name
        if col_map["name"] is not None:
            name = _cell(col_map["name"])
        elif col_map["fname"] is not None:
            name = (_cell(col_map["fname"]) + " " + _cell(col_map["lname"])).strip()
        else:
            name = ""

        if not name or name.lower() in ("name", "driver", ""):
            continue

        # Some pages (e.g. 030518) have an unlabeled col 0 holding the competition class
        # while the explicit "Class" column holds the PAX class. Prefer col 0 in that case.
        if col_map["_col0_blank"] and n > 0 and re.match(r'^[A-Z]{2,5}$', cells_raw[0].strip()):
            car_class = cells_raw[0].strip()
        else:
            car_class = _cell(col_map["class"])
        raw_num   = _cell(col_map["car_num"])

        # Build car description
        if col_map["car"] is not None:
            car = _cell(col_map["car"])
        elif col_map["make"] is not None:
            car = (_cell(col_map["make"]) + " " + _cell(col_map["model"])).strip()
        else:
            car = ""

        # Car number: strip trailing class suffix (e.g. "56 EP" → "56")
        # or use the 2004 CarID value as-is.
        num_match = re.match(r'^(\d+)', raw_num)
        if num_match:
            car_number = num_match.group(1)
        else:
            car_number = raw_num  # CarID like "34ASP"

        # Extract class from CarID if not explicit
        if not car_class and raw_num:
            m = re.search(r'[A-Z][A-Z0-9]*$', raw_num)
            if m:
                car_class = m.group(0)

        if not car_class:
            continue

        # Best / PAX times — fall back to last few columns when headers are absent
        if col_map["best"] is not None:
            best_time = safe_float(_cell(col_map["best"]))
        else:
            best_time = safe_float(cells_raw[-3]) if n >= 3 else None

        if col_map["pax"] is not None:
            pax_time = safe_float(_cell(col_map["pax"]))
        else:
            pax_time = safe_float(cells_raw[-1]) if n >= 1 else None

        pax_index = safe_float(_cell(col_map["pax_index"])) if col_map["pax_index"] else None

        results.append(DriverResult(
            event_date=date_str,
            event_year=int(year),
            car_class=car_class,
            car_number=car_number,
            name=name,
            car=car,
            best_time=best_time,
            pax_index=pax_index,
            pax_time=pax_time,
            source_url=url,
            scrape_method="static_html",
        ))

    return results


# ---------------------------------------------------------------------------
# Playwright scraper for Finish-Time JS pages
# ---------------------------------------------------------------------------

def parse_finish_time_page(page_html: str, url: str, year: str, date_str: str) -> list[DriverResult]:
    """
    Parse a fully-rendered Finish-Time page.
    The table structure has: Position | Class | Number | Name | Car | Run1... | Best | Diff | PAX
    Or variations depending on the FT version.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    results = []

    # Find the main results table — look for tables with "Name" header
    tables = soup.find_all("table")
    for table in tables:
        first_row = table.find("tr")
        if not first_row:
            continue
        headers = [td.get_text(strip=True).lower() for td in first_row.find_all(["td", "th"])]

        if "name" not in headers and "driver" not in headers:
            continue

        # Map column indices
        if "name" in headers:
            name_idx = headers.index("name")
        elif "driver" in headers:
            name_idx = headers.index("driver")
        else:
            continue

        car_idx = headers.index("car") if "car" in headers else None
        class_idx = next((i for i, h in enumerate(headers) if "class" in h), None)
        number_idx = next((i for i, h in enumerate(headers) if h in ("no", "#", "number", "car #", "carid")), None)
        best_idx = next((i for i, h in enumerate(headers) if h in ("best", "best run", "time")), None)
        pax_idx = next((i for i, h in enumerate(headers) if "pax" in h and "index" not in h), None)
        pax_index_idx = next((i for i, h in enumerate(headers) if "index" in h), None)

        current_class = "UNKNOWN"
        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if not cells:
                continue

            # Detect class separator rows BEFORE checking name_idx length.
            # These are single-cell rows like "AS  [Street]" or just "GS".
            if len(cells) == 1 or (class_idx is not None and len(cells) <= class_idx + 1):
                if cells[0]:
                    # Strip description suffix: "AS\xa0\xa0[Street]" -> "AS"
                    m = re.match(r'^([A-Z][A-Z0-9]*)', cells[0].strip())
                    current_class = m.group(1) if m else cells[0].strip()
                continue

            if len(cells) <= name_idx:
                continue

            name = cells[name_idx].strip()
            if not name or name.lower() in ("name", ""):
                continue

            if class_idx is not None and class_idx < len(cells):
                cls = cells[class_idx].strip()
                if cls:
                    current_class = cls

            car = cells[car_idx].strip() if car_idx is not None and car_idx < len(cells) else ""
            car_number = cells[number_idx].strip() if number_idx is not None and number_idx < len(cells) else ""
            best_time = safe_float(cells[best_idx]) if best_idx is not None and best_idx < len(cells) else None
            pax_time = safe_float(cells[pax_idx]) if pax_idx is not None and pax_idx < len(cells) else None
            pax_index = safe_float(cells[pax_index_idx]) if pax_index_idx is not None and pax_index_idx < len(cells) else None
            # Finish-Time 4.0 has no "Best" column — derive from pax_time / pax_index
            if best_time is None and pax_time is not None and pax_index and pax_index > 0:
                best_time = round(pax_time / pax_index, 3)

            # Derive class from CarID (e.g. "9SS" -> "SS") when not set from a separator row
            if current_class == "UNKNOWN" and car_number:
                m = re.match(r'^\d+([A-Z][A-Z0-9-]*)$', car_number)
                if m:
                    current_class = m.group(1)

            results.append(DriverResult(
                event_date=date_str,
                event_year=int(year),
                car_class=current_class,
                car_number=car_number,
                name=name,
                car=car,
                best_time=best_time,
                pax_index=pax_index,
                pax_time=pax_time,
                source_url=url,
                scrape_method="playwright",
            ))

    return results


def scrape_with_playwright(url: str, year: str, date_str: str) -> list[DriverResult]:
    """Use Playwright to render JS pages and extract results."""
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        print("  ⚠  Playwright not installed. Run: pip install playwright && playwright install chromium")
        return []

    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000)

            # Wait for Finish-Time to finish loading
            # It typically replaces "Loading data..." with table content
            try:
                page.wait_for_function(
                    "() => !document.body.innerText.includes('Loading data')",
                    timeout=15000
                )
            except PlaywrightTimeout:
                print(f"  ⚠  Timeout waiting for JS render: {url}")

            time.sleep(1)  # brief extra wait for table population
            html = page.content()
            browser.close()

        results = parse_finish_time_page(html, url, year, date_str)
    except Exception as e:
        print(f"  ✗  Playwright error for {url}: {e}")

    return results


# ---------------------------------------------------------------------------
# Page type detection
# ---------------------------------------------------------------------------

def is_js_rendered(html: str) -> bool:
    """Return True if page uses JS rendering (Finish-Time modern style)."""
    lhtml = html.lower()
    return (
        "loading data" in lhtml
        or "loading... please wait" in lhtml  # Finish-Time 2.x AJAX style
        or "hostType()" in html  # Finish-Time 3.x wrapper page
    )


def fetch_static(url: str, session: requests.Session) -> Optional[str]:
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  ✗  Fetch error: {e}")
        return None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT,
            event_year INTEGER,
            car_class TEXT,
            car_number TEXT,
            name TEXT,
            car TEXT,
            best_time REAL,
            pax_index REAL,
            pax_time REAL,
            source_url TEXT,
            scrape_method TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_name ON results(name COLLATE NOCASE)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_year ON results(event_year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON results(event_date)")
    conn.commit()
    return conn


def insert_results(conn: sqlite3.Connection, results: list[DriverResult]):
    conn.executemany(
        """INSERT INTO results
           (event_date, event_year, car_class, car_number, name, car,
            best_time, pax_index, pax_time, source_url, scrape_method)
           VALUES (:event_date, :event_year, :car_class, :car_number, :name, :car,
                   :best_time, :pax_index, :pax_time, :source_url, :scrape_method)""",
        [asdict(r) for r in results]
    )
    conn.commit()


def already_scraped(conn: sqlite3.Connection, url: str) -> bool:
    row = conn.execute("SELECT 1 FROM results WHERE source_url = ? LIMIT 1", (url,)).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Main scrape loop
# ---------------------------------------------------------------------------

def scrape_all(
    db_path: str = "nhscc_results.db",
    year_filter: Optional[int] = None,
    start_year: Optional[int] = None,
    export_csv: bool = False,
    delay: float = 1.0,
):
    conn = init_db(db_path)
    session = requests.Session()
    session.headers["User-Agent"] = "NHSCC-Scraper/1.0 (club admin tool)"

    events = EVENT_URLS
    if year_filter:
        events = [(y, d, u) for y, d, u in events if int(y) == year_filter]
    elif start_year:
        events = [(y, d, u) for y, d, u in events if int(y) >= start_year]

    total = len(events)
    all_results: list[DriverResult] = []

    print(f"Scraping {total} events → {db_path}")
    print("─" * 60)

    for i, (year, date_str, url) in enumerate(events, 1):
        print(f"[{i:3}/{total}] {year}-{date_str}  {url}")

        if already_scraped(conn, url):
            print("  ✓  Already in DB, skipping.")
            continue

        html = fetch_static(url, session)
        if not html:
            print("  ✗  Could not fetch page.")
            time.sleep(delay)
            continue

        if is_js_rendered(html):
            print("  ⚙  JS-rendered (Finish-Time) — using Playwright...")
            results = scrape_with_playwright(url, year, date_str)
        else:
            print("  ⚙  Static HTML — parsing directly...")
            results = parse_static_html(html, url, year, date_str)
            if not results:
                results = parse_finish_time_page(html, url, year, date_str)

        if results:
            insert_results(conn, results)
            all_results.extend(results)
            print(f"  ✓  {len(results)} driver entries saved.")
        else:
            print("  ⚠  No results parsed (may need manual inspection).")

        time.sleep(delay)

    print("\n─" * 60)
    total_rows = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    total_names = conn.execute("SELECT COUNT(DISTINCT name) FROM results").fetchone()[0]
    print(f"Done. {total_rows} total entries, {total_names} unique names in DB.")

    if export_csv:
        csv_path = db_path.replace(".db", ".csv")
        rows = conn.execute("SELECT * FROM results ORDER BY event_date, car_class, name").fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM results LIMIT 0").description]
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        print(f"CSV exported → {csv_path}")

    conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def lookup_person(name: str, db_path: str) -> None:
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        return
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    pattern = f"%{name}%"

    matched_names = [r[0] for r in conn.execute(
        "SELECT DISTINCT name FROM results WHERE name LIKE ? COLLATE NOCASE ORDER BY name",
        (pattern,),
    ).fetchall()]

    if not matched_names:
        print(f"No results found for: {name!r}")
        conn.close()
        return

    if len(matched_names) > 1:
        print(f"Matched {len(matched_names)} names: {', '.join(matched_names)}\n")

    rows = conn.execute(
        """
        SELECT event_date, car_class, car_number, car, best_time, pax_time, source_url
        FROM results
        WHERE name LIKE ? COLLATE NOCASE
        ORDER BY event_date DESC
        """,
        (pattern,),
    ).fetchall()
    conn.close()

    last = rows[0]
    print(f"Last seen: {last['event_date']}  class={last['car_class']}  #{last['car_number']}  car={last['car']}  best={last['best_time']}  pax={last['pax_time']}")
    print(f"           {last['source_url']}")
    print(f"\nAll appearances ({len(rows)}):")
    for row in rows:
        bt = f"{row['best_time']:.3f}" if row["best_time"] else "—"
        pt = f"{row['pax_time']:.3f}" if row["pax_time"] else "—"
        print(f"  {row['event_date']}  {row['car_class']:<6}  #{row['car_number']:<4}  best={bt}  pax={pt}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape NHSCC autocross results")
    parser.add_argument("--year", type=int, help="Scrape only this year")
    parser.add_argument("--start-year", type=int, help="Scrape from this year onward")
    parser.add_argument("--output", default="nhscc_results.db", help="SQLite output path (default: nhscc_results.db)")
    parser.add_argument("--csv", action="store_true", help="Also export a CSV file")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests (default: 1.0)")
    parser.add_argument("--lookup", metavar="NAME", help="Look up a person by name and exit")
    args = parser.parse_args()

    if args.lookup:
        lookup_person(args.lookup, args.output)
    else:
        scrape_all(
            db_path=args.output,
            year_filter=args.year,
            start_year=args.start_year,
            export_csv=args.csv,
            delay=args.delay,
        )
