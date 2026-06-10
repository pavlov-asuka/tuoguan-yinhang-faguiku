from __future__ import annotations

import csv
import html
import json
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import html as lxml_html
from pypdf import PdfReader

from build_search_index import build_index


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "01_法规原文库"
TEXT_ROOT = ROOT / "02_文本抽取库"
META_ROOT = ROOT / "03_元数据台账"
TOPIC_ROOT = ROOT / "04_托管业务专题地图"
ENTRY_ROOT = ROOT / "00_入口与索引"
UNRESOLVED_ROOT = ROOT / "99_unresolved"
SUPPLEMENTAL_RULES_PATH = META_ROOT / "supplemental_rules.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass
class Source:
    url: str = ""
    source_type: str = "正文页"
    note: str = ""
    attach: bool = True
    local_path: str = ""
    local_text_path: str = ""


@dataclass
class Rule:
    id: str
    title: str
    category: str
    layer: str
    issuer: str = ""
    rule_no: str = ""
    publish_date: str = ""
    effective_date: str = ""
    current_status: str = "待核验"
    priority: str = "P2"
    is_core: str = "否"
    source_type: str = ""
    business_tags: str = ""
    notes: str = ""
    npc_search: bool = False
    sources: list[Source] = field(default_factory=list)


def rules() -> list[Rule]:
    return [
        Rule("001", "中华人民共和国证券投资基金法", "01_上位法律", "法律", "全国人民代表大会常务委员会", publish_date="2015-04-24", effective_date="2015-04-24", current_status="现行有效", priority="P0", is_core="是", business_tags="托管人法定职责;基金财产独立性;持有人保护", npc_search=True),
        Rule("002", "中华人民共和国证券法", "01_上位法律", "法律", "全国人民代表大会常务委员会", current_status="现行有效", priority="P0", is_core="是", business_tags="证券交易;信息披露;市场禁止行为", npc_search=True),
        Rule("003", "中华人民共和国银行业监督管理法", "01_上位法律", "法律", "全国人民代表大会常务委员会", current_status="现行有效", priority="P0", is_core="是", business_tags="商业银行监管;机构监管", npc_search=True),
        Rule("004", "中华人民共和国信托法", "01_上位法律", "法律", "全国人民代表大会常务委员会", publish_date="2001-04-28", effective_date="2001-10-01", current_status="现行有效", priority="P0", is_core="是", business_tags="信托关系;受托义务;财产独立性", npc_search=True),

        Rule("005", "证券投资基金托管业务管理办法", "02_行政法规与部门规章", "部门规章", "中国证监会、原银保监会", "证监会令第172号", "2020-07-10", "2020-07-10", "现行有效", "P0", "是", "正文页", "托管资格;托管人职责;内控;监督边界;退出机制", "2025年修订草案仅作辅助线索，不替代现行172号令", sources=[Source("https://www.csrc.gov.cn/csrc/c101877/c1029534/content.shtml")]),
        Rule("006", "基金管理公司投资管理人员管理指导意见", "02_行政法规与部门规章", "规范性文件", "中国证监会", "证监会公告〔2009〕3号", "2009-03-17", "2009-04-01", "现行有效", "P1", "否", "正文页", "人员治理;信息隔离;投资管理", sources=[Source("https://www.csrc.gov.cn/csrc/c101877/c1029635/content.shtml")]),
        Rule("007", "基金托管人资格核准相关行政许可服务指南", "02_行政法规与部门规章", "行政许可配套文件", "中国证监会", current_status="辅助索引", priority="P1", is_core="否", source_type="服务指南页", business_tags="托管资格申请;行政许可", notes="辅助索引，非主规则正文", sources=[Source("https://www.csrc.gov.cn/csrc/c101968/c4179850/content.shtml", "服务指南页")]),

        Rule("008", "公开募集证券投资基金运作管理办法", "03_证监会公募基金一般运作规则", "部门规章", "中国证监会", "证监会令第104号", "2014-07-07", "2014-08-08", "现行有效", "P0", "是", "正文页;附件", "募集;运作;申赎;清算;持有人大会", sources=[Source("https://www.csrc.gov.cn/csrc/c101877/c1029566/content.shtml"), Source("https://www.csrc.gov.cn/csrc/c106256/c1653978/content.shtml", "规章库正文页")]),
        Rule("009", "公开募集证券投资基金信息披露管理办法", "03_证监会公募基金一般运作规则", "部门规章", "中国证监会", "证监会令第158号", "2019-07-26", "2019-09-01", "现行有效", "P0", "是", "正文页", "净值披露;定期报告;临时公告;未公开信息", sources=[Source("https://www.csrc.gov.cn/csrc/c101877/c1029542/content.shtml"), Source("https://www.csrc.gov.cn/csrc/c106256/c1653985/content.shtml", "规章库正文页")]),
        Rule("010", "关于实施《公开募集证券投资基金信息披露管理办法》有关问题的规定", "03_证监会公募基金一般运作规则", "规范性文件", "中国证监会", "证监会公告〔2019〕18号", "2019-07-26", "2019-09-01", "现行有效", "P0", "是", "正文页", "信息披露执行;披露媒介;过渡安排", sources=[Source("https://www.csrc.gov.cn/csrc/c101877/c1029541/content.shtml")]),
        Rule("011", "公开募集开放式证券投资基金流动性风险管理规定", "03_证监会公募基金一般运作规则", "规范性文件", "中国证监会", "证监会公告〔2017〕12号", "2017-08-31", "2017-10-01", "现行有效", "P0", "是", "正文页;附件PDF", "流动性风险;巨额赎回;流动性工具;估值公允性", sources=[Source("https://www.csrc.gov.cn/csrc/c101877/c1029552/content.shtml", "正文页", attach=False), Source("https://www.csrc.gov.cn/csrc/c101877/c1029552/1029552/files/%E9%99%84%E4%BB%B6%EF%BC%9A%E3%80%8A%E5%85%AC%E5%BC%80%E5%8B%9F%E9%9B%86%E5%BC%80%E6%94%BE%E5%BC%8F%E8%AF%81%E5%88%B8%E6%8A%95%E8%B5%84%E5%9F%BA%E9%87%91%E6%B5%81%E5%8A%A8%E6%80%A7%E9%A3%8E%E9%99%A9%E7%AE%A1%E7%90%86%E8%A7%84%E5%AE%9A%E3%80%8B.pdf", "附件PDF", attach=False)]),
        Rule("012", "公开募集证券投资基金侧袋机制指引（试行）", "03_证监会公募基金一般运作规则", "规范性文件", "中国证监会", "证监会公告〔2020〕41号", "2020-07-10", "2020-08-01", "现行有效", "P0", "是", "正文页;附件", "侧袋机制;难估值资产;费用;信披;托管人职责", sources=[Source("https://www.csrc.gov.cn/csrc/c101877/c1029533/content.shtml")]),
        Rule("013", "公开募集证券投资基金风险准备金监督管理暂行办法", "03_证监会公募基金一般运作规则", "部门规章", "中国证监会", "证监会令第94号", "2013-09-24", "2014-01-01", "现行有效", "P0", "是", "正文页;附件", "风险准备金;托管人计提;风险补偿", sources=[Source("https://www.csrc.gov.cn/csrc/c101895/c1037888/content.shtml"), Source("https://www.csrc.gov.cn/csrc/c106256/c1653975/1653975/files/57b202cc56a34e5c8eb704de8dbcc1e7.pdf", "附件PDF", attach=False)]),
        Rule("014", "中国证监会关于证券投资基金估值业务的指导意见", "03_证监会公募基金一般运作规则", "规范性文件", "中国证监会", "证监会公告〔2017〕13号", "2017-09-05", "2017-09-05", "现行有效", "P0", "是", "正文页", "估值;估值复核;公允价值;估值责任", sources=[Source("https://www.csrc.gov.cn/csrc/c101896/c1039133/content.shtml")]),
        Rule("015", "关于基金投资非公开发行股票等流通受限证券有关问题的通知", "03_证监会公募基金一般运作规则", "规范性文件", "中国证监会", "证监基金字〔2006〕141号", "2006-07-20", "2006-07-20", "现行有效", "P1", "是", "证监会法规库正文页", "流通受限证券;估值;投资限制", sources=[Source("https://neris.csrc.gov.cn/falvfagui/rdqsHeader/mainbody?navbarId=3&secFutrsLawId=4114755b94bf47c0a515385231bfa837", "法规库正文页")]),
        Rule("016", "关于证券投资基金投资资产支持证券有关事项的通知", "03_证监会公募基金一般运作规则", "规范性文件", "中国证监会", "证监基金字〔2006〕93号", "2006-05-14", "2006-05-14", "待核验", "P1", "是", "公报PDF", "资产支持证券;估值;披露;风险管理", "先纳入证监会公报PDF，后续建议定位法规库独立正文页", sources=[Source("https://www.csrc.gov.cn/csrc/c100024/c1492317/1492317/files/7a2e3df6cdbc4855aba258d78ecadc1e.pdf", "公报PDF", attach=False)]),
        Rule("017", "关于规范证券投资基金运作中证券交易行为的通知", "03_证监会公募基金一般运作规则", "规范性文件", "中国证监会", "证监发〔2001〕29号", "2001-02-26", "", "历史失效", "P2", "否", "", "证券交易;历史规则", "检索到证监会废止目录线索，暂不纳入现行主库", sources=[]),
        Rule("018", "关于完善证券投资基金交易席位制度有关问题的通知", "03_证监会公募基金一般运作规则", "规范性文件", "中国证监会", "证监基金字〔2007〕48号", "2007-02-16", "2017-04-01", "历史失效", "P2", "否", "证监会法规库正文页", "交易席位;佣金分仓;托管人监督;历史规则", "证监会法规库显示已被废止；现行交易费用规则另列", sources=[Source("https://neris.csrc.gov.cn/falvfagui/rdqsHeader/mainbody?navbarId=3&secFutrsLawId=7d18bc91053442cb82fbe07fa70f99e2", "法规库正文页")]),
        Rule("018B", "公开募集证券投资基金证券交易费用管理规定", "03_证监会公募基金一般运作规则", "规范性文件", "中国证监会", "", "2024-04-19", "2024-07-01", "现行有效", "P1", "是", "正文页;附件", "证券交易费用;佣金;交易管理;托管监督", "补充现行规则，用于替代已废止交易席位制度通知", sources=[Source("https://www.csrc.gov.cn/csrc/c101954/c7475004/content.shtml")]),

        Rule("019", "货币市场基金监督管理办法", "04_公募基金产品专项规则", "部门规章", "中国证监会、中国人民银行", "证监会令第120号", "2015-12-17", "2016-02-01", "现行有效", "P0", "是", "附件PDF", "货币基金;偏离度;流动性;快速赎回", sources=[Source("https://www.csrc.gov.cn/csrc/c106256/c1654015/1654015/files/52c60ebbeb5642e08f9f629bb8ed190e.pdf", "附件PDF", attach=False)]),
        Rule("020", "公开募集证券投资基金运作指引第2号——基金中基金指引", "04_公募基金产品专项规则", "规范性文件", "中国证监会", "证监会公告〔2016〕20号", "2016-09-11", "2016-09-11", "现行有效", "P0", "是", "正文页", "FOF;投资比例;穿透;关联交易", sources=[Source("https://www.csrc.gov.cn/csrc/c101877/c1029555/content.shtml")]),
        Rule("021", "公开募集证券投资基金运作指引第1号——商品期货交易型开放式基金指引", "04_公募基金产品专项规则", "规范性文件", "中国证监会", "", "", "", "待核验", "P2", "否", "", "商品期货ETF;保证金;估值;申赎", "未在本轮定位到正式发布页，暂入待核验", sources=[]),
        Rule("022A", "合格境内机构投资者境外证券投资管理试行办法", "04_公募基金产品专项规则", "部门规章", "中国证监会", "证监会令第46号", "2007-06-18", "2007-07-05", "现行有效", "P1", "是", "规章库正文页", "QDII;境外投资;境外托管;外汇;信披", sources=[Source("https://www.csrc.gov.cn/csrc/c106256/c1653919/content.shtml"), Source("https://www.csrc.gov.cn/csrc/c101932/c1044480/content.shtml")]),
        Rule("022B", "关于实施《合格境内机构投资者境外证券投资管理试行办法》有关问题的通知", "04_公募基金产品专项规则", "规范性文件", "中国证监会", "证监发〔2007〕81号", "2007-06-18", "2007-07-05", "现行有效", "P1", "是", "地方监管局转载官方页", "QDII;境外托管;投资限制;估值;信披", "本轮先收上海监管局官方转载页，后续可追证监会法规库独立正文", sources=[Source("https://www.csrc.gov.cn/shanghai/c105564/c1270195/content.shtml", "地方监管局转载官方页")]),
        Rule("023", "公开募集基础设施证券投资基金指引（试行）", "04_公募基金产品专项规则", "规范性文件", "中国证监会", "证监会公告〔2020〕54号", "2020-08-07", "2020-08-07", "现行有效", "P1", "是", "正文页;附件", "公募REITs;基础设施基金;托管;运营", sources=[Source("https://www.csrc.gov.cn/csrc/c101877/c1029531/content.shtml")]),

        Rule("025A", "中华人民共和国增值税法", "05A_税法与公募基金增值税规则", "法律", "全国人民代表大会常务委员会", "", "2024-12-25", "2026-01-01", "现行有效", "P1", "否", "税务总局法规库正文页", "应税交易;存款利息;免税项目;税收优惠", sources=[Source("https://fgk.chinatax.gov.cn/zcfgk/c100009/c5237365/content.html", "税务总局法规库正文页")]),
        Rule("025B", "中华人民共和国增值税法实施条例", "05A_税法与公募基金增值税规则", "行政法规", "国务院", "国务院令第826号", "2025-12-25", "2026-01-01", "现行有效", "P1", "否", "税务总局法规库正文页", "金融服务;计税;征管衔接", sources=[Source("https://fgk.chinatax.gov.cn/zcfgk/c100010/c5246349/content.html", "税务总局法规库正文页")]),
        Rule("025C", "财政部 税务总局关于增值税征税具体范围有关事项的公告", "05A_税法与公募基金增值税规则", "税收规范性文件", "财政部、税务总局", "财政部 税务总局公告2026年第9号", "2026-01-30", "2026-01-01", "现行有效", "P1", "否", "税务总局法规库正文页", "贷款服务;金融商品持有期间收益;征税范围", sources=[Source("https://fgk.chinatax.gov.cn/zcfgk/c102416/c5247431/content.html", "税务总局法规库正文页")]),
        Rule("025D", "财政部 税务总局关于资管产品增值税有关问题的通知", "05A_税法与公募基金增值税规则", "税收规范性文件", "财政部、税务总局", "财税〔2017〕56号", "2017-06-30", "2018-01-01", "现行有效", "P1", "否", "税务总局法规库正文页", "资管产品运营业务;简易计税;3%征收率;管理人范围;公募基金", "采用税务总局政策法规库稳定正文页", sources=[Source("https://fgk.chinatax.gov.cn/zcfgk/c102416/c5202526/content.html", "税务总局法规库正文页")]),
        Rule("025D1", "财政部 税务总局关于租入固定资产进项税额抵扣等增值税政策的通知", "05A_税法与公募基金增值税规则", "税收规范性文件", "财政部、税务总局", "财税〔2017〕90号", "2017-12-25", "2018-01-01", "现行有效", "P2", "否", "税务系统官方转载", "资管产品运营业务销售额;贷款服务;金融商品转让;债券估值", "作为财税〔2017〕56号配套口径保存，重点关注第五条", sources=[Source("https://guangdong.chinatax.gov.cn/gdsw/zjfg/2018-01/05/content_3c4a8e382145466f92331abc870e4f97.shtml", "税务系统官方转载")]),
        Rule("025E", "财政部 税务总局关于增值税法施行后增值税优惠政策衔接事项的公告", "05A_税法与公募基金增值税规则", "税收规范性文件", "财政部、税务总局", "财政部 税务总局公告2026年第10号", "2026-01-30", "2026-01-01", "现行有效", "P1", "否", "税务总局法规库正文页", "金融同业往来利息;同业存单;买入返售;优惠衔接", sources=[Source("https://fgk.chinatax.gov.cn/zcfgk/c102416/c5247434/content.html", "税务总局法规库正文页")]),
        Rule("025F", "财政部 税务总局关于国债等债券利息收入增值税政策的公告", "05A_税法与公募基金增值税规则", "税收规范性文件", "财政部、税务总局", "财政部 税务总局公告2025年第4号", "2025-07-31", "2025-08-08", "现行有效", "P1", "否", "税务总局法规库正文页", "债券利息收入;国债;地方政府债;金融债;税务划断", sources=[Source("https://fgk.chinatax.gov.cn/zcfgk/c102416/c5242161/content.html", "税务总局法规库正文页")]),
        Rule("025G1", "国家税务总局关于起征点标准等增值税征管事项的公告", "05A_税法与公募基金增值税规则", "税收规范性文件", "国家税务总局", "国家税务总局公告2026年第4号", "2026-01-30", "", "现行有效", "P2", "否", "税务总局法规库正文页", "征管配套;债券利息;月销售额口径", sources=[Source("https://fgk.chinatax.gov.cn/zcfgk/c100012/c5247426/content.html", "税务总局法规库正文页")]),
        Rule("025G2", "财政部 税务总局关于延续实施境外机构投资境内债券市场企业所得税、增值税政策的公告", "05A_税法与公募基金增值税规则", "税收规范性文件", "财政部、税务总局", "财政部 税务总局公告2026年第5号", "2026-01-13", "2026-01-01", "现行有效", "P2", "否", "税务系统官方转载", "QDII;跨境债券;境外机构;增值税优惠;债券利息收入", "清单原广东税务线索已404，本轮改用广东税务系统官方转载页；后续可继续核对中央法规库稳定页", sources=[Source("https://guangdong.chinatax.gov.cn/gdsw/zjfg/2026-01/16/content_fd12a26e977d4c5bb2bdc9066ae5e4a2.shtml", "税务系统官方转载")]),

        Rule("025", "商业银行托管业务监督管理办法（试行）", "05_银行业监管与行业自律", "部门规章", "国家金融监督管理总局", "", "2025-03-21", "", "现行有效", "P0", "是", "规则页;发布说明", "商业银行托管;机构监管;业务范围;内控;监督管理", sources=[Source("https://www.nfra.gov.cn/cn/view/pages/rulesDetail.html?docId=1237183", "规则页"), Source("https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId=1237329&itemId=917", "发布说明")]),
        Rule("026", "商业银行资产托管业务指引", "05_银行业监管与行业自律", "行业自律规则", "中国银行业协会", "", "2019-03-18", "2019-03-18", "现行有效", "P1", "是", "协会正文页", "托管职责;资产保管;账户;估值核算;清算;投资监督", sources=[Source("https://www.china-cba.net/Index/showw/catid/130/id/19843", "协会正文页")]),
        Rule("027", "商业银行内部控制、信息科技、外包管理、数据治理等托管配套规则", "05_银行业监管与行业自律", "配套规则组", "金融监管总局、人民银行、网信办等", "", "", "", "待扩展", "P2", "否", "", "内控;信息科技;外包;数据治理;网络安全", "本轮仅建主题占位，后续按规则组扩展", sources=[]),

        Rule("028", "中国证券投资基金业协会——基金托管及服务栏目总入口", "06_AMAC托管运营估值清算细则", "栏目入口", "中国证券投资基金业协会", "", "", "", "辅助索引", "P1", "否", "栏目页", "AMAC托管;估值;清算;栏目入口", "辅助索引，不作为规则正文", sources=[Source("https://www.amac.org.cn/businessservices_2025/trusteeshipbusiness_2912/", "栏目页")]),
        Rule("029", "基金托管及服务——政策法规入口", "06_AMAC托管运营估值清算细则", "栏目入口", "中国证券投资基金业协会", "", "", "", "辅助索引", "P1", "否", "栏目页", "AMAC政策法规;托管服务", sources=[Source("https://fg.amac.org.cn/governmentrules_3854/zcgz_zlgz/jjtgjfw/", "栏目页")]),
        Rule("030", "证券投资基金港股通投资资金清算和会计核算估值业务指引（试行）", "06_AMAC托管运营估值清算细则", "AMAC操作细则", "中国证券投资基金业协会", "", "", "", "现行有效", "P1", "是", "附件PDF", "港股通;资金清算;会计核算;估值", sources=[Source("https://www.amac.org.cn/xwfb/hydt/202106/P020231126371218718148.pdf", "附件PDF", attach=False)]),
        Rule("031", "证券投资基金参与转融通证券出借业务会计核算和估值业务指引（试行）", "06_AMAC托管运营估值清算细则", "AMAC操作细则", "中国证券投资基金业协会", "", "2019-06-21", "", "现行有效", "P1", "是", "通知页;附件PDF", "转融通;证券出借;会计核算;估值", sources=[Source("https://www.amac.org.cn/xwfb/xhyw/201912/t20191231_15878.html", "通知页", attach=False), Source("https://www.amac.org.cn/xwfb/hydt/202105/P020231126371234153504.pdf", "附件PDF", attach=False)]),
        Rule("032", "证券投资基金投资信用衍生品估值指引（试行）", "06_AMAC托管运营估值清算细则", "AMAC估值细则", "中国证券投资基金业协会", "中基协发〔2019〕1号", "2019-01-18", "2019-01-18", "现行有效", "P1", "是", "通知页;附件PDF", "信用衍生品;估值;会计处理", sources=[Source("https://www.amac.org.cn/businessservices_2025/trusteeshipbusiness_2912/tgfwgzglgj/tgfwtzyj/202105/t20210531_11788.html", "通知页", attach=False), Source("https://www.amac.org.cn/xwfb/tzgg/201901/P020231126367143196433.pdf", "附件PDF", attach=False)]),
        Rule("033", "证券投资基金参与同业存单会计核算和估值业务指引（试行）", "06_AMAC托管运营估值清算细则", "AMAC会计核算与估值细则", "中国证券投资基金业协会", "", "", "", "现行有效", "P1", "是", "附件PDF", "同业存单;会计核算;估值;定期报告列示", sources=[Source("https://www.amac.org.cn/fwdt/wyb/jgdjhcpbeian/smjjglrdjhcpba/xgzc/202001/P020231126372106723208.pdf", "附件PDF", attach=False)]),
        Rule("034", "证券投资基金投资流通受限股票估值指引（试行）", "06_AMAC托管运营估值清算细则", "AMAC估值细则", "中国证券投资基金业协会", "中基协发〔2017〕6号", "2017-09-04", "2017-09-04", "现行有效", "P1", "是", "通知页;附件PDF", "流通受限股票;估值;托管估值复核", sources=[Source("https://fg.amac.org.cn/governmentrules_3854/zcgz_zlgz/jjtgjfw/zlgz_jjfw_gzyw/202408/t20240828_25952.html", "通知页", attach=False), Source("https://www.amac.org.cn/xwfb/tzgg/201709/P020231126367070343127.pdf", "附件PDF", attach=False)]),
        Rule("035", "证券投资基金侧袋机制操作细则（试行）", "06_AMAC托管运营估值清算细则", "AMAC操作细则", "中国证券投资基金业协会", "", "2020-10-30", "2020-10-30", "现行有效", "P1", "是", "通知页;附件PDF", "侧袋机制;份额处理;估值;运营落地", sources=[Source("https://www.amac.org.cn/xwfb/xhyw/202010/t20201030_15950.html", "通知页", attach=False), Source("https://www.amac.org.cn/xwfb/hydt/202106/P020231126371237550716.pdf", "附件PDF", attach=False)]),
        Rule("036", "公开募集证券投资基金会计核算业务指引", "06_AMAC托管运营估值清算细则", "AMAC会计核算规则", "中国证券投资基金业协会", "", "", "", "待核验", "P1", "否", "", "公募基金会计核算;账务处理", "本轮未确认正式实施版本；清单中的征求意见稿不纳入现行主库", sources=[]),
        Rule("037", "基金估值标准体系相关规则", "06_AMAC托管运营估值清算细则", "规则组", "中国证券投资基金业协会", "", "", "", "待扩展", "P2", "否", "栏目页", "基金估值标准;第三方估值;债券估值", "本轮保存栏目页，后续可按估值标准规则组逐条展开", sources=[Source("https://www.amac.org.cn/businessservices_2025/jjfwyw/", "栏目页")]),
        Rule("038", "公募基金行业合规管理手册", "06_AMAC托管运营估值清算细则", "行业手册", "中国证券投资基金业协会", "", "2025-01-22", "", "辅助资料", "P3", "否", "附件PDF", "合规管理;托管运营;辅助资料", "辅助资料，不作为强制规则", sources=[Source("https://www.amac.org.cn/hyyj/hjtj/202005/P020250122588393150509.pdf", "附件PDF", attach=False)]),
        Rule("039", "证券投资基金会计核算操作实务手册", "06_AMAC托管运营估值清算细则", "行业手册", "中国证券投资基金业协会", "", "2024-05-30", "", "辅助资料", "P3", "否", "附件PDF", "会计核算;操作实务;辅助资料", "手册标明仅供参考，不作为必然依据", sources=[Source("https://www.amac.org.cn/hyyj/hjtj/202405/P020240530424712416888.pdf", "附件PDF", attach=False)]),

        Rule("040", "AMBERS / 公募基金业务 / 托管数据报送相关规则", "07_数据报送与人员管理", "业务报送规则组", "中国证券投资基金业协会", "", "", "", "待扩展", "P2", "否", "栏目页", "AMBERS;数据报送;报送模板", "本轮保存入口页，后续按通知和模板展开", sources=[Source("https://www.amac.org.cn/fwdt/wyb/sjbs/", "栏目页")]),
        Rule("041", "基金从业人员管理规则", "07_数据报送与人员管理", "行业自律规则", "中国证券投资基金业协会", "", "2023-11-24", "", "现行有效", "P0", "是", "发布页;附件PDF", "从业人员;人员管理;职业规范", sources=[Source("https://www.amac.org.cn/xwfb/xhyw/202311/t20231124_24119.html", "发布页", attach=False), Source("https://www.amac.org.cn/xwfb/xhyw/202311/P020231126420114603815.pdf", "附件PDF", attach=False)]),
        Rule("042", "关于实施《基金从业人员管理规则》有关事项的规定", "07_数据报送与人员管理", "配套规则", "中国证券投资基金业协会", "", "2023-11-24", "", "现行有效", "P0", "是", "发布页;附件PDF", "从业人员;实施安排;人员管理", sources=[Source("https://www.amac.org.cn/xwfb/xhyw/202311/t20231124_24119.html", "发布页", attach=False), Source("https://www.amac.org.cn/xwfb/xhyw/202311/P020231126420116567190.pdf", "附件PDF", attach=False)]),
        Rule("043", "资产管理业务综合报送平台 / 公募用户 / 数据备份等配套通知", "07_数据报送与人员管理", "系统通知规则组", "中国证券投资基金业协会", "", "", "", "待扩展", "P2", "否", "", "报送平台;数据备份;系统规则", "本轮仅建主题占位", sources=[]),

        Rule("044", "中国结算——基金登记结算、清算交收、账户业务规则", "08_交易所与登记结算基础设施规则", "基础设施规则组", "中国结算", "", "", "", "待扩展", "P2", "否", "官网入口", "登记结算;清算交收;账户;ETF;LOF;港股通", "市场基础设施规则数量大，后续按专题抓取", sources=[Source("https://www.chinaclear.cn/", "官网入口")]),
        Rule("045", "上海证券交易所——基金业务规则", "08_交易所与登记结算基础设施规则", "基础设施规则组", "上海证券交易所", "", "", "", "待扩展", "P2", "否", "官网入口", "ETF;基金上市;REITs;申购赎回", "后续按专题抓取", sources=[Source("https://www.sse.com.cn/", "官网入口")]),
        Rule("046", "深圳证券交易所——基金业务规则", "08_交易所与登记结算基础设施规则", "基础设施规则组", "深圳证券交易所", "", "", "", "待扩展", "P2", "否", "官网入口", "ETF;LOF;REITs;申购赎回", "后续按专题抓取", sources=[Source("https://www.szse.cn/", "官网入口")]),
        Rule("047", "银行间市场——债券、回购、同业存单、结算规则", "08_交易所与登记结算基础设施规则", "基础设施规则组", "CFETS、中债登、上清所", "", "", "", "待扩展", "P2", "否", "官网入口", "银行间债券;回购;同业存单;结算", "后续按专题抓取", sources=[Source("https://www.cfets.com.cn/", "官网入口"), Source("https://www.chinabond.com.cn/", "官网入口"), Source("https://www.shclearing.com/", "官网入口")]),
        Rule("048", "港股通 / 互联互通结算规则", "08_交易所与登记结算基础设施规则", "基础设施规则组", "沪深交易所、中国结算、香港交易所", "", "", "", "待扩展", "P2", "否", "", "港股通;互联互通;结算", "后续按专题抓取", sources=[]),

        Rule("049", "QDII / 境外托管相关规则组", "09_跨境与港股通_QDII_REITs_专项", "专项规则组", "证监会、外汇局、人民银行", "", "", "", "待扩展", "P2", "否", "", "QDII;境外托管;外汇;跨境结算", "本轮已收QDII办法及实施通知，外汇配套待后续展开", sources=[]),
        Rule("050", "公募 REITs 托管相关规则组", "09_跨境与港股通_QDII_REITs_专项", "专项规则组", "证监会、沪深交易所、中国结算", "", "", "", "待扩展", "P2", "否", "", "公募REITs;托管;信披;运营", "本轮已收证监会基础设施基金指引，交易所和中登配套待后续展开", sources=[]),
        Rule("051", "场外衍生品、信用保护工具、收益互换等估值/结算规则组", "09_跨境与港股通_QDII_REITs_专项", "专项规则组", "证监会、AMAC、交易所、银行间市场", "", "", "", "待扩展", "P2", "否", "", "信用衍生品;场外衍生品;估值;结算", "本轮已收AMAC信用衍生品估值指引，其他规则待后续展开", sources=[]),

        Rule("052", "基金合同、托管协议、招募说明书、产品资料概要的格式指引或范本", "10_合同格式与辅助资料", "格式指引规则组", "证监会、AMAC、交易所", "", "", "", "待扩展", "P3", "否", "", "基金合同;托管协议;招募说明书;产品资料概要", "本轮仅建主题占位", sources=[]),
        Rule("053", "公募基金信息披露 XBRL 模板", "10_合同格式与辅助资料", "模板规则组", "AMAC、证监会、基金电子披露平台", "", "", "", "待扩展", "P3", "否", "", "XBRL;定期报告;信披模板", "本轮仅建主题占位", sources=[]),
        Rule("054", "中国证券投资基金电子披露网站相关规则", "10_合同格式与辅助资料", "披露通道规则组", "证监会、基金电子披露平台", "", "", "", "待扩展", "P3", "否", "", "电子披露;公告披露;披露通道", "本轮仅建主题占位", sources=[]),
    ]


def source_from_dict(data: dict[str, Any]) -> Source:
    return Source(
        url=data.get("url", ""),
        source_type=data.get("source_type", "正文页"),
        note=data.get("note", ""),
        attach=data.get("attach", True),
        local_path=data.get("local_path", ""),
        local_text_path=data.get("local_text_path", ""),
    )


def rule_from_dict(data: dict[str, Any]) -> Rule:
    values = {
        "id": data["id"],
        "title": data["title"],
        "category": data["category"],
        "layer": data["layer"],
        "issuer": data.get("issuer", ""),
        "rule_no": data.get("rule_no", ""),
        "publish_date": data.get("publish_date", ""),
        "effective_date": data.get("effective_date", ""),
        "current_status": data.get("current_status", "待核验"),
        "priority": data.get("priority", "P2"),
        "is_core": data.get("is_core", "否"),
        "source_type": data.get("source_type", ""),
        "business_tags": data.get("business_tags", ""),
        "notes": data.get("notes", ""),
        "npc_search": data.get("npc_search", False),
        "sources": [source_from_dict(s) for s in data.get("sources", [])],
    }
    return Rule(**values)


def apply_rule_update(rule: Rule, data: dict[str, Any]) -> None:
    for field_name in [
        "title", "category", "layer", "issuer", "rule_no", "publish_date",
        "effective_date", "current_status", "priority", "is_core",
        "source_type", "business_tags", "notes", "npc_search",
    ]:
        if field_name in data:
            setattr(rule, field_name, data[field_name])
    if "sources" in data:
        rule.sources = [source_from_dict(s) for s in data.get("sources", [])]


def all_rules() -> list[Rule]:
    base_rules = rules()
    if not SUPPLEMENTAL_RULES_PATH.exists():
        return base_rules

    data = json.loads(SUPPLEMENTAL_RULES_PATH.read_text(encoding="utf-8"))
    by_id = {rule.id: rule for rule in base_rules}
    ordered = list(base_rules)
    for item in data:
        rid = item["id"]
        if rid in by_id:
            apply_rule_update(by_id[rid], item)
        else:
            rule = rule_from_dict(item)
            by_id[rid] = rule
            ordered.append(rule)
    return ordered


def ensure_dirs() -> None:
    for path in [ENTRY_ROOT, RAW_ROOT, TEXT_ROOT, META_ROOT, TOPIC_ROOT, UNRESOLVED_ROOT]:
        path.mkdir(parents=True, exist_ok=True)
    for category in sorted({r.category for r in all_rules()}):
        (RAW_ROOT / category).mkdir(parents=True, exist_ok=True)
        (TEXT_ROOT / category).mkdir(parents=True, exist_ok=True)


def safe_name(value: str, max_len: int = 90) -> str:
    value = html.unescape(value)
    value = re.sub(r"[<>:\"/\\|?*\r\n\t]", "_", value)
    value = re.sub(r"\s+", "", value)
    value = value.strip(" ._")
    return value[:max_len] or "untitled"


def request_bytes(url: str, *, method: str = "GET", data: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[bytes, dict[str, str], str]:
    url = iri_to_uri(url)
    req_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    with urllib.request.urlopen(req, timeout=35) as resp:
        return resp.read(), dict(resp.headers), resp.geturl()


def iri_to_uri(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/%")
    query = urllib.parse.quote(parts.query, safe="=&%")
    fragment = urllib.parse.quote(parts.fragment, safe="")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, fragment))


def decode_text(data: bytes, headers: dict[str, str] | None = None) -> str:
    charset = None
    if headers:
        match = re.search(r"charset=([\w-]+)", headers.get("Content-Type", ""), re.I)
        if match:
            charset = match.group(1)
    for enc in [charset, "utf-8", "gb18030", "gbk", "big5"]:
        if not enc:
            continue
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="ignore")


def guess_ext(url: str, content_type: str = "") -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for ext in [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".zip", ".ofd", ".html", ".shtml", ".htm"]:
        if path.endswith(ext):
            return ".html" if ext in [".shtml", ".htm"] else ext
    content_type = content_type.lower()
    if "pdf" in content_type:
        return ".pdf"
    if "wordprocessingml" in content_type:
        return ".docx"
    if "msword" in content_type:
        return ".doc"
    if "spreadsheetml" in content_type:
        return ".xlsx"
    if "excel" in content_type:
        return ".xls"
    if "html" in content_type or "text/plain" in content_type:
        return ".html"
    return ".bin"


def extract_html_text(data: bytes, headers: dict[str, str]) -> str:
    text = decode_text(data, headers)
    try:
        doc = lxml_html.fromstring(text)
    except Exception:
        return text
    for bad in doc.xpath("//script|//style|//noscript"):
        bad.drop_tree()
    body = doc.text_content()
    lines = [re.sub(r"\s+", " ", line).strip() for line in body.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_pdf_text(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n\n".join(p for p in parts if p.strip())
    except Exception as exc:
        return f"[PDF文本抽取失败] {exc}"


def extract_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
        doc = lxml_html.fromstring(xml)
        texts = doc.xpath("//*[local-name()='t']/text()")
        return "\n".join(t.strip() for t in texts if t.strip())
    except Exception as exc:
        return f"[DOCX文本抽取失败] {exc}"


def write_text_for_file(raw_file: Path, text_dir: Path, headers: dict[str, str] | None = None) -> Path | None:
    ext = raw_file.suffix.lower()
    text = ""
    if ext == ".pdf":
        text = extract_pdf_text(raw_file)
    elif ext == ".docx":
        text = extract_docx_text(raw_file)
    elif ext in [".html", ".htm"]:
        text = extract_html_text(raw_file.read_bytes(), headers or {})
    elif ext in [".txt"]:
        text = decode_text(raw_file.read_bytes(), headers or {})
    else:
        return None
    text_dir.mkdir(parents=True, exist_ok=True)
    target = text_dir / f"{raw_file.stem}.txt"
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


def discover_attachments(base_url: str, data: bytes, headers: dict[str, str]) -> list[tuple[str, str]]:
    try:
        doc = lxml_html.fromstring(decode_text(data, headers))
    except Exception:
        return []
    attachments: list[tuple[str, str]] = []
    for a in doc.xpath("//a[@href]"):
        href = a.get("href") or ""
        label = re.sub(r"\s+", " ", a.text_content()).strip()
        if href.startswith("javascript:") or href.startswith("#"):
            continue
        full = urllib.parse.urljoin(base_url, href)
        path = urllib.parse.urlparse(full).path.lower()
        looks_like_file = any(path.endswith(ext) for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".ofd"])
        if looks_like_file or "附件" in label:
            attachments.append((full, label or Path(path).name))
    seen = set()
    unique = []
    for item in attachments:
        if item[0] not in seen:
            seen.add(item[0])
            unique.append(item)
    return unique[:10]


def download_to(url: str, target: Path) -> tuple[Path, dict[str, str], str]:
    data, headers, final_url = request_bytes(url)
    ext = guess_ext(final_url, headers.get("Content-Type", ""))
    if target.suffix.lower() != ext:
        target = target.with_suffix(ext)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target, headers, final_url


def npc_lookup(title: str) -> dict[str, Any] | None:
    payload = {
        "searchRange": 1,
        "sxrq": [],
        "gbrq": [],
        "searchType": 1,
        "sxx": [],
        "gbrqYear": [],
        "flfgCodeId": [],
        "zdjgCodeId": [],
        "searchContent": title,
        "pageNum": 1,
        "pageSize": 10,
    }
    data, _, _ = request_bytes(
        "https://flk.npc.gov.cn/law-search/search/list",
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json;charset=utf-8", "Accept": "application/json"},
    )
    result = json.loads(data.decode("utf-8"))
    rows = result.get("rows") or []
    plain = lambda s: re.sub(r"<[^>]+>", "", s or "")
    for row in rows:
        if plain(row.get("title")) == title:
            return row
    return rows[0] if rows else None


def npc_detail(bbbs: str) -> dict[str, Any] | None:
    url = "https://flk.npc.gov.cn/law-search/search/flfgDetails?" + urllib.parse.urlencode({"bbbs": bbbs})
    data, _, _ = request_bytes(url, headers={"Accept": "application/json"})
    result = json.loads(data.decode("utf-8"))
    return result.get("data")


def download_npc_rule(rule: Rule, raw_dir: Path, text_dir: Path) -> tuple[list[Path], list[Path], list[str]]:
    notes: list[str] = []
    raw_files: list[Path] = []
    text_files: list[Path] = []
    row = npc_lookup(rule.title)
    if not row:
        return raw_files, text_files, [f"NPC未检索到：{rule.title}"]
    bbbs = row["bbbs"]
    detail = npc_detail(bbbs) or {}
    meta_path = raw_dir / f"{rule.id}_{safe_name(rule.title)}_npc_detail.json"
    meta_path.write_text(json.dumps({"search_row": row, "detail": detail}, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    raw_files.append(meta_path)
    text_files.append(write_text_for_file(meta_path.with_suffix(".txt"), text_dir) if False else None)  # keep linter quiet
    for fmt in ["pdf", "docx"]:
        url = f"https://flk.npc.gov.cn/law-search/download/mobile?format={fmt}&bbbs={bbbs}&fileId="
        try:
            data, headers, _ = request_bytes(url)
            target = raw_dir / f"{rule.id}_{safe_name(rule.title)}_国家法律法规数据库.{fmt}"
            target.write_bytes(data)
            raw_files.append(target)
            text_target = write_text_for_file(target, text_dir, headers)
            if text_target:
                text_files.append(text_target)
            time.sleep(0.2)
        except Exception as exc:
            notes.append(f"NPC {fmt}下载失败：{exc}")
    return [p for p in raw_files if p], [p for p in text_files if p], notes


def download_rule(rule: Rule) -> dict[str, Any]:
    raw_dir = RAW_ROOT / rule.category / f"{rule.id}_{safe_name(rule.title)}"
    text_dir = TEXT_ROOT / rule.category / f"{rule.id}_{safe_name(rule.title)}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    raw_files: list[Path] = []
    text_files: list[Path] = []
    errors: list[str] = []
    source_urls: list[str] = []

    existing_raw = sorted(p for p in raw_dir.rglob("*") if p.is_file())
    existing_text = sorted(p for p in text_dir.rglob("*") if p.is_file())
    if existing_raw:
        source_urls.extend(["https://flk.npc.gov.cn/" if rule.npc_search else ""] + [s.url or s.local_path for s in rule.sources])
        source_urls = [u for u in source_urls if u]
        raw_files.extend(existing_raw)
        text_files.extend(existing_text)
        return {
            "id": rule.id,
            "title": rule.title,
            "category": rule.category,
            "layer": rule.layer,
            "issuer": rule.issuer,
            "rule_no": rule.rule_no,
            "publish_date": rule.publish_date,
            "effective_date": rule.effective_date,
            "current_status": rule.current_status,
            "priority": rule.priority,
            "is_core": rule.is_core,
            "source_type": rule.source_type,
            "business_tags": rule.business_tags,
            "source_url": "; ".join(source_urls),
            "local_path": "; ".join(str(p.relative_to(ROOT)) for p in raw_files),
            "text_path": "; ".join(str(p.relative_to(ROOT)) for p in text_files),
            "file_type": "; ".join(sorted({p.suffix.lower().lstrip(".") for p in raw_files})),
            "notes": (rule.notes + "; " if rule.notes else "") + "续跑时复用已下载文件",
            "errors": "",
            "downloaded_count": len(raw_files),
        }

    if rule.npc_search:
        try:
            r, t, e = download_npc_rule(rule, raw_dir, text_dir)
            raw_files.extend(r)
            text_files.extend(t)
            errors.extend(e)
            source_urls.append("https://flk.npc.gov.cn/")
        except Exception as exc:
            errors.append(f"NPC下载失败：{exc}")

    for idx, src in enumerate(rule.sources, start=1):
        source_ref = src.url or src.local_path
        if source_ref:
            source_urls.append(source_ref)
        try:
            stem = f"{rule.id}_{safe_name(rule.title)}_{idx:02d}_{safe_name(src.source_type)}"
            target = raw_dir / stem
            if src.local_path:
                source_path = (ROOT / src.local_path).resolve()
                if not source_path.is_file():
                    raise FileNotFoundError(f"本地来源不存在：{src.local_path}")
                downloaded = target.with_suffix(source_path.suffix)
                shutil.copy2(source_path, downloaded)
                headers: dict[str, str] = {}
                final_url = src.url or src.local_path
            else:
                downloaded, headers, final_url = download_to(src.url, target)
            raw_files.append(downloaded)
            if src.local_text_path:
                text_source = (ROOT / src.local_text_path).resolve()
                if not text_source.is_file():
                    raise FileNotFoundError(f"本地文本来源不存在：{src.local_text_path}")
                text_dir.mkdir(parents=True, exist_ok=True)
                text_target = text_dir / f"{downloaded.stem}.txt"
                shutil.copy2(text_source, text_target)
            else:
                text_target = write_text_for_file(downloaded, text_dir, headers)
            if text_target:
                text_files.append(text_target)
            if src.attach and downloaded.suffix.lower() == ".html":
                data = downloaded.read_bytes()
                for a_idx, (attach_url, label) in enumerate(discover_attachments(final_url, data, headers), start=1):
                    try:
                        a_stem = f"{rule.id}_{safe_name(rule.title)}_附件{a_idx:02d}_{safe_name(label)}"
                        a_file, a_headers, _ = download_to(attach_url, raw_dir / a_stem)
                        raw_files.append(a_file)
                        a_text = write_text_for_file(a_file, text_dir, a_headers)
                        if a_text:
                            text_files.append(a_text)
                        time.sleep(0.2)
                    except Exception as exc:
                        errors.append(f"附件下载失败 {attach_url}: {exc}")
            time.sleep(0.2)
        except urllib.error.HTTPError as exc:
            errors.append(f"{src.url} HTTP {exc.code}: {exc.reason}")
        except Exception as exc:
            errors.append(f"{src.url} 下载失败：{exc}")

    return {
        "id": rule.id,
        "title": rule.title,
        "category": rule.category,
        "layer": rule.layer,
        "issuer": rule.issuer,
        "rule_no": rule.rule_no,
        "publish_date": rule.publish_date,
        "effective_date": rule.effective_date,
        "current_status": rule.current_status,
        "priority": rule.priority,
        "is_core": rule.is_core,
        "source_type": rule.source_type,
        "business_tags": rule.business_tags,
        "source_url": "; ".join(source_urls),
        "local_path": "; ".join(str(p.relative_to(ROOT)) for p in raw_files),
        "text_path": "; ".join(str(p.relative_to(ROOT)) for p in text_files),
        "file_type": "; ".join(sorted({p.suffix.lower().lstrip(".") for p in raw_files})),
        "notes": rule.notes,
        "errors": "; ".join(errors),
        "downloaded_count": len(raw_files),
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def html_anchor(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value).strip("-")
    return value or "item"


def split_path_field(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(";") if item.strip()]


def local_file_href(path: str) -> str:
    href = "../" + path.replace("\\", "/")
    return urllib.parse.quote(href, safe="/._-~%()（）《》【】[];：:—+")


def file_label(path: str) -> str:
    return re.split(r"[\\/]", path)[-1]


def write_html_index(rows: list[dict[str, Any]], now: str) -> None:
    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)

    sidebar_parts = []
    content_parts = []
    for category_index, (category, items) in enumerate(by_category.items(), start=1):
        cat_id = f"cat-{category_index:02d}-{html_anchor(category)}"
        sidebar_parts.append(
            f'<a class="category-link" href="#{cat_id}">'
            f'<span>{html.escape(category)}</span><span>{len(items)}</span></a>'
        )
        sidebar_parts.append('<div class="rule-links">')
        for item in items:
            rule_id = f"rule-{html_anchor(item['id'])}"
            sidebar_parts.append(
                f'<a href="#{rule_id}"><span>{html.escape(item["id"])}</span>'
                f'{html.escape(item["title"])}</a>'
            )
        sidebar_parts.append("</div>")

        cards = []
        for item in items:
            rule_id = f"rule-{html_anchor(item['id'])}"
            raw_paths = [p for p in split_path_field(item.get("local_path", "")) if not p.lower().endswith(".json")]
            if raw_paths:
                links = "\n".join(
                    f'<a class="file-link" href="{local_file_href(path)}" target="_blank" rel="noopener">'
                    f'<span>{html.escape(file_label(path))}</span></a>'
                    for path in raw_paths
                )
            else:
                links = '<span class="empty">暂无本地原文文件</span>'

            source_urls = split_path_field(item.get("source_url", ""))
            source_links = "\n".join(
                f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">{html.escape(url)}</a>'
                if re.match(r"^https?://", url, re.I)
                else f'<a href="{local_file_href(url)}" target="_blank" rel="noopener">{html.escape(url)}</a>'
                for url in source_urls
            ) or '<span class="empty">暂无官方来源链接</span>'

            cards.append(
                f"""
                <article class="rule-card" id="{rule_id}">
                  <div class="rule-title">
                    <span class="rule-id">{html.escape(item['id'])}</span>
                    <h3>{html.escape(item['title'])}</h3>
                  </div>
                  <div class="badges">
                    <span>{html.escape(item['priority'])}</span>
                    <span>{html.escape(item['current_status'])}</span>
                    <span>{html.escape(item['source_type'] or '未标注来源类型')}</span>
                  </div>
                  <dl class="meta-grid">
                    <div><dt>发文机关</dt><dd>{html.escape(item['issuer'] or '未标注')}</dd></div>
                    <div><dt>文号</dt><dd>{html.escape(item['rule_no'] or '未标注')}</dd></div>
                    <div><dt>发布日期</dt><dd>{html.escape(item['publish_date'] or '未标注')}</dd></div>
                    <div><dt>生效日期</dt><dd>{html.escape(item['effective_date'] or '未标注')}</dd></div>
                    <div><dt>业务标签</dt><dd>{html.escape(item['business_tags'] or '未标注')}</dd></div>
                  </dl>
                  <div class="link-block">
                    <h4>本地法规原文</h4>
                    <div class="file-links">{links}</div>
                  </div>
                  <details>
                    <summary>官方来源</summary>
                    <div class="source-links">{source_links}</div>
                  </details>
                </article>
                """
            )
        content_parts.append(
            f"""
            <section class="category-section" id="{cat_id}">
              <div class="section-heading">
                <h2>{html.escape(category)}</h2>
                <span>{len(items)} 条</span>
              </div>
              {''.join(cards)}
            </section>
            """
        )

    total_files = sum(int(row.get("downloaded_count") or 0) for row in rows)
    unresolved_count = sum(1 for row in rows if row.get("errors"))
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>公募基金托管法规知识库总目录</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #20242a;
      --muted: #606975;
      --line: #d8dde5;
      --accent: #1f6f78;
      --accent-soft: #e3f2f2;
      --warn: #8a5b16;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.55;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);
      min-height: 100vh;
    }}
    aside {{
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      border-right: 1px solid var(--line);
      background: #eef3f4;
      padding: 20px 16px;
    }}
    aside h1 {{
      margin: 0 0 6px;
      font-size: 22px;
      letter-spacing: 0;
    }}
    .subtitle {{
      margin: 0 0 18px;
      color: var(--muted);
      font-size: 13px;
    }}
    nav a {{
      color: inherit;
      text-decoration: none;
    }}
    .category-link {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 9px 10px;
      border-radius: 6px;
      color: #143f46;
      font-weight: 650;
    }}
    .category-link:hover, .rule-links a:hover {{
      background: var(--accent-soft);
      color: #0f5962;
    }}
    .rule-links {{
      margin: 2px 0 10px;
      border-left: 1px solid #c9d7da;
      padding-left: 8px;
    }}
    .rule-links a {{
      display: grid;
      grid-template-columns: 52px 1fr;
      gap: 8px;
      padding: 6px 8px;
      border-radius: 6px;
      color: #39434d;
      font-size: 13px;
    }}
    main {{
      padding: 28px min(5vw, 56px) 64px;
    }}
    .hero {{
      margin-bottom: 24px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 18px;
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: 30px;
      letter-spacing: 0;
    }}
    .stats {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }}
    .stat {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 12px;
      color: var(--muted);
    }}
    .stat strong {{
      color: var(--text);
      margin-right: 4px;
    }}
    .category-section {{
      scroll-margin-top: 20px;
      margin-top: 32px;
    }}
    .section-heading {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 12px;
    }}
    .section-heading h2 {{
      margin: 0;
      font-size: 23px;
      letter-spacing: 0;
    }}
    .section-heading span {{
      color: var(--muted);
    }}
    .rule-card {{
      scroll-margin-top: 20px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      margin: 12px 0;
    }}
    .rule-title {{
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 10px;
      align-items: start;
    }}
    .rule-id {{
      min-width: 48px;
      border-radius: 6px;
      background: var(--accent);
      color: white;
      text-align: center;
      padding: 3px 7px;
      font-weight: 700;
    }}
    .rule-card h3 {{
      margin: 0;
      font-size: 18px;
      letter-spacing: 0;
    }}
    .badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 12px 0;
    }}
    .badges span {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 9px;
      color: var(--muted);
      font-size: 13px;
      background: #fafbfc;
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 18px;
      margin: 0 0 12px;
    }}
    .meta-grid div {{
      min-width: 0;
    }}
    dt {{
      color: var(--muted);
      font-size: 12px;
    }}
    dd {{
      margin: 0;
      overflow-wrap: anywhere;
    }}
    .link-block h4 {{
      margin: 12px 0 8px;
      font-size: 14px;
      color: var(--accent);
    }}
    .file-links, .source-links {{
      display: grid;
      gap: 7px;
    }}
    .file-link, .source-links a {{
      display: block;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      color: #164f58;
      background: #fbfdfd;
      text-decoration: none;
      overflow-wrap: anywhere;
    }}
    .file-link:hover, .source-links a:hover {{
      border-color: var(--accent);
      background: var(--accent-soft);
    }}
    details {{
      margin-top: 12px;
    }}
    summary {{
      cursor: pointer;
      color: var(--muted);
    }}
    .empty {{
      color: var(--warn);
    }}
    @media (max-width: 860px) {{
      .layout {{
        display: block;
      }}
      aside {{
        position: relative;
        height: auto;
        max-height: 55vh;
      }}
      main {{
        padding: 22px 16px 48px;
      }}
      .meta-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside>
      <h1>总目录</h1>
      <p class="subtitle">生成时间：{html.escape(now)}</p>
      <nav>{''.join(sidebar_parts)}</nav>
    </aside>
    <main>
      <header class="hero">
        <h1>公募基金托管法规知识库总目录</h1>
        <p>左侧目录可跳转到分类或具体法规；右侧“本地法规原文”链接指向本项目下已下载的原文文件。</p>
        <div class="stats">
          <div class="stat"><strong>{len(rows)}</strong>条法规/规则</div>
          <div class="stat"><strong>{len(by_category)}</strong>个分类</div>
          <div class="stat"><strong>{total_files}</strong>个本地文件</div>
          <div class="stat"><strong>{unresolved_count}</strong>条下载错误</div>
        </div>
      </header>
      {''.join(content_parts)}
    </main>
  </div>
</body>
</html>
"""
    (ENTRY_ROOT / "总目录.html").write_text(document, encoding="utf-8", newline="\n")


def write_markdown_indexes(rows: list[dict[str, Any]]) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    table_rows = []
    for row in rows:
        table_rows.append(
            f"| {row['id']} | {row['priority']} | {row['category']} | {row['title']} | {row['current_status']} | {row['downloaded_count']} | {row['business_tags']} |"
        )
    table = "\n".join(table_rows)
    (META_ROOT / "rules_index.md").write_text(
        "# 法规元数据台账\n\n"
        f"生成时间：{now}\n\n"
        "| ID | 优先级 | 分类 | 文件名称 | 状态 | 原文文件数 | 业务标签 |\n"
        "|---|---|---|---|---|---:|---|\n"
        f"{table}\n",
        encoding="utf-8",
        newline="\n",
    )

    (ENTRY_ROOT / "README.md").write_text(
        "# 公募基金托管法规知识库\n\n"
        "## 核心用途\n\n"
        "- 沉淀商业银行开展公募基金托管业务相关的法规原文、可检索文本、结构化元数据和业务专题地图。\n"
        "- 支撑面向用户的法规咨询：回答问题时优先检索本地法规库，再按需联网核验现行性、最新修订和官方来源。\n"
        "- 维护规则状态与依据链，明确区分现行有效、历史失效、待核验、待扩展和辅助资料，避免把征求意见稿、新闻稿、解读或行业手册当作现行强制依据。\n\n"
        "## 知识库架构\n\n"
        "- `00_入口与索引/`：知识库入口、HTML 总目录导航和更新记录。\n"
        "- `01_法规原文库/`：按法规分类保存官方网页、PDF、附件等原始材料。\n"
        "- `02_文本抽取库/`：保存从原文中抽取出的可检索文本，用于法规问答和条款定位。\n"
        "- `03_元数据台账/`：维护规则编号、名称、状态、来源、路径、优先级和业务标签等结构化信息。\n"
        "- `04_托管业务专题地图/`：按托管业务场景组织规则，作为法规咨询时的业务检索入口。\n"
        "- `99_unresolved/`：记录待核验、待扩展、历史失效或来源不完整的事项。\n"
        "- `tools/`：保存知识库构建脚本，用于下载、抽取、生成索引和刷新专题地图。\n\n"
        "## 来源优先级与核验规则\n\n"
        "1. 优先国家法律法规数据库、证监会、金融监管总局、AMAC、税务总局、交易所、中国结算等官方来源。\n"
        "2. 正文页和附件均保留；栏目页、通知页、官方转载页只作为辅助索引或待核验线索。\n"
        "3. 征求意见稿、起草说明、解读文章、新闻稿不进入现行主库；可进入辅助资料或 unresolved。\n"
        "4. 每条规则保留 `current_status`、`validity_checked_at`、`source_type`、`business_tags` 字段。\n"
        "5. 发现新旧版本冲突时，先标记待核验，不用草案替代正式现行规则。\n",
        encoding="utf-8",
        newline="\n",
    )

    write_html_index(rows, now)

    (ENTRY_ROOT / "更新记录.md").write_text(
        "# 更新记录\n\n"
        f"- {now}：重建知识库索引，应用 supplemental_rules.json，补齐 unresolved 中可核验的正式规则、失效入口和规则组拆分项；同步刷新总目录、台账、专题地图和待核验清单。\n"
        "- 2026-05-29：建立第一版知识库骨架，下载 P0 主干规则、税法模块、AMAC 已定位细则和若干官方入口页。\n",
        encoding="utf-8",
        newline="\n",
    )


def write_topic_map(rows: list[dict[str, Any]]) -> None:
    topics = {
        "托管人法定职责": ["001", "005", "008", "025", "026"],
        "证券市场与银行监管基础": ["002", "003", "004", "008", "009"],
        "基金财产独立性": ["001", "004", "005", "026"],
        "托管资格与内控": ["003", "005", "007", "025", "026", "027", "027A", "027B", "027C", "027D", "027E"],
        "投资人员与职业规范": ["006", "041", "042"],
        "投资监督": ["001", "005", "008", "011", "020", "026", "018B"],
        "证券交易行为与交易费用": ["002", "017", "018", "018B"],
        "风险准备金与风险补偿": ["013"],
        "资产支持证券": ["016"],
        "估值复核": ["005", "014", "024", "030", "030A", "030B", "032", "033", "034", "035", "037A", "037B", "047D", "039", "051A"],
        "会计核算": ["024", "030", "030A", "030B", "031", "033", "037B", "039"],
        "AMAC托管运营规则入口与体系": ["028", "029", "036", "037", "038"],
        "清算交收": ["030", "031", "044", "044A", "044B", "047", "047A", "047B", "047C", "048C"],
        "信息披露复核": ["009", "010", "011", "012", "023", "053", "054"],
        "业绩比较基准与投资风格约束": ["055", "055A", "055B", "009", "053A"],
        "侧袋机制": ["012", "024", "035"],
        "数据报送与人员管理": ["006", "040", "041", "042", "043"],
        "市场基础设施规则组": ["044", "045", "046", "047", "048"],
        "ETF与场内基金业务": ["044", "044A", "044B", "045", "045A", "046", "046A", "046B"],
        "港股通": ["030", "048", "048A", "048B", "048C"],
        "转融通": ["031"],
        "同业存单": ["033", "025E"],
        "流通受限股票": ["015", "034"],
        "货币基金": ["019", "011", "014"],
        "FOF": ["020"],
        "商品期货ETF": ["021", "030B"],
        "黄金ETF与贵金属": ["030B"],
        "QDII": ["049", "022A", "022B", "049A"],
        "公募REITs": ["050", "023", "045B", "050A", "050B", "050C"],
        "合同与产品文件": ["052", "052A", "052B", "052C"],
        "电子披露与XBRL": ["053A", "053B", "054A"],
        "信用衍生品与场外工具": ["051", "051A", "032", "051B"],
        "固定收益品种估值": ["014", "037B", "047D"],
        "银行间债券与回购": ["047", "047A", "047B", "047C", "047D", "037B"],
        "增值税与债券利息": ["025A", "025B", "025C", "025D", "025D1", "025E", "025F", "025G1", "025G2"],
    }
    row_map = {r["id"]: r for r in rows}
    lines = ["# 托管业务专题地图", ""]
    for topic, ids in topics.items():
        lines.extend([f"## {topic}", ""])
        for rid in ids:
            row = row_map.get(rid)
            if row:
                lines.append(f"- `{rid}` {row['title']}（{row['current_status']}）")
        lines.append("")
    (TOPIC_ROOT / "托管业务专题地图.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_unresolved(rows: list[dict[str, Any]]) -> None:
    selected = [
        r for r in rows
        if r["current_status"] in ["待核验", "待扩展"]
        or r["errors"]
    ]
    lines = ["# 待核验与未完成项目", ""]
    for row in selected:
        lines.append(f"## {row['id']} {row['title']}")
        lines.append(f"- 状态：{row['current_status']}")
        lines.append(f"- 分类：{row['category']}")
        lines.append(f"- 来源：{row['source_url'] or '待检索'}")
        lines.append(f"- 本轮原文文件数：{row['downloaded_count']}")
        if row["errors"]:
            lines.append(f"- 错误/提示：{row['errors']}")
        if row["notes"]:
            lines.append(f"- 备注：{row['notes']}")
        lines.append("")
    (UNRESOLVED_ROOT / "unresolved.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def copy_source_checklist() -> None:
    for src in [ROOT / "中国公募基金托管法规体系下载清单_详细版_含细则_含税法.md", Path("C:/Users/Administrator/Desktop/中国公募基金托管法规体系下载清单_详细版_含细则_含税法.md")]:
        if src.exists():
            target = ENTRY_ROOT / "原始下载清单.md"
            if src.resolve() != target.resolve():
                shutil.copy2(src, target)
            return


def main() -> None:
    ensure_dirs()
    copy_source_checklist()

    rows: list[dict[str, Any]] = []
    for rule in all_rules():
        print(f"[{rule.id}] {rule.title}")
        rows.append(download_rule(rule))

    fields = [
        "id", "priority", "category", "title", "layer", "issuer", "rule_no",
        "publish_date", "effective_date", "current_status", "is_core",
        "source_type", "business_tags", "source_url", "local_path",
        "text_path", "file_type", "downloaded_count", "notes", "errors",
    ]
    write_csv(META_ROOT / "rules_index.csv", rows, fields)
    write_csv(META_ROOT / "download_log.csv", rows, fields)
    (META_ROOT / "rules_index.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    write_markdown_indexes(rows)
    write_topic_map(rows)
    write_unresolved(rows)
    search_index_summary = build_index(ROOT)

    summary = {
        "total_rules": len(rows),
        "rules_with_files": sum(1 for r in rows if r["downloaded_count"]),
        "total_files": sum(int(r["downloaded_count"]) for r in rows),
        "rules_with_errors": sum(1 for r in rows if r["errors"]),
        "search_index": search_index_summary,
    }
    (META_ROOT / "build_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
