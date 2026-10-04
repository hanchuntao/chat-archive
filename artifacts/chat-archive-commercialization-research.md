# chat-archive 商业化调研报告：能力组合 → 付费点 → 收费模式 → 差异化

> 调研日期：2026-10-04　|　调研方法：general_search 找官网/官方文档/公开报价页，关键定价经 web_fetch 核验
> 说明：闭源商业产品一律标注「闭源商业产品」；定价以官网公开页面为准，拿不到精确数字标注「定价未公开/需询价」。

---

## 一、产品卡片（共 20 个，覆盖 6 大类）

### 1. 腾讯 ima（ima.copilot）
- 官网: https://ima.qq.com | 形态: 闭源商业产品（腾讯C端AI知识管家）
- 定位: "会思考的知识库"，搜/读/写一体化的个人知识管理 copilot
- 核心付费能力: 知识库精准问答（原文溯源）、copilot 长期记忆、AI笔记创作、订阅公开知识库、skill 扩展
- 定价模式: **基础功能完全免费**；copilot 高级能力走「算力」计费，新人发 500 算力，用完充值。来源：https://developer.cloud.tencent.com/techpedia/202613/20563 ；https://ima.qq.com
- 目标客群: C端个人（自媒体、学生、写作者），正扩展到团队/agent 派活场景
- 与 chat-archive 能力的映射: chat-archive 已有 `knowledge/` 本地知识库 + `kb-sync` 对接 ima API（config.json `knowledge.ima`）。即 chat-archive 把群聊清洗后自动灌进 ima，再用 ima 的 copilot 做问答——**chat-archive 是 ima 的"群聊数据采集器/清洗器"，ima 是问答层**。
- 可借鉴的商业模式: 「基础处理免费 + AI提炼算力按量充值」——chat-archive 的 LLM 提炼（DeepSeek/OpenAI兼容）天然适合走 token credit 包。

### 2. 微伴助手
- 官网: https://weibanzhushou.com | 形态: 闭源商业产品（企微SCRM SaaS）
- 定位: 企业微信生态私域运营 SCRM，40+功能覆盖获客/转化/运营/管理
- 核心付费能力: 渠道活码、客户标签分层、群SOP、**群聊质检**、消息存档、词频分析、客户之声（聊天意图分析）、销售/服务扩展包
- 定价模式: 基础版 7000元/年（含50席位）；营销扩展包 7000元/年；销售扩展包 600元/账号/年；服务扩展包 600元/账号/年；**会话扩展包（会话存档+质检）300元/账号/年**。来源：https://www.36dianping.com/vs/imi1.html ；定价页 https://doc.weibanzhushou.com/pricing（数字动态加载）
- 目标客群: 有企业微信的中小商家/品牌私域团队
- 与 chat-archive 能力的映射: chat-archive 的「客服考核(证据化) + 质检信号分类 + 群活跃度 + 词频/关键词趋势」≈ 微伴的「群聊质检 + 词频分析 + 客户之声 + 成员统计」。**差异：微伴必须走企微官方会话存档接口（合规、要企业认证、接口费另付），chat-archive 吃的是导出的群聊TXT/JSON，不碰企微接口、不挑企业主体**。
- 可借鉴的商业模式: 「基础版打包 + 按席位加购扩展包」——质检/会话类按席位单独卖包，正是 chat-archive 可拆分的付费点。

### 3. 尘锋 SCRM
- 官网: https://www.dustess.com | 形态: 闭源商业产品（企微SCRM，深耕医美/家装/律所/汽车）
- 定位: 获客→转化→交易→增长全链条私域运营，"系统+人才+服务"
- 核心付费能力: 线索自动分配/回收、智能SOP、**AI会话质检（DeepSeek驱动，识别私单飞单/辱骂/敏感词）**、客户画像自动总结、订单商品管理
- 定价模式: 标准版 1200元/人/年（CRM+营销+订单+商品，不含会话存档）；企业版 1800元/人/年（全套）；定制版 20万元起。阶梯价：5-19人 1080元/人/年。来源：https://www.woshipm.com/pd/5878422.html ；https://m.36dianping.com/space/2146
- 目标客群: 中大型销售型企业（高客单、长决策链行业）
- 与 chat-archive 能力的映射: chat-archive 的 `assessment.rules`（私域导流/私下返现/绝对化话术/辱骂客户/敷衍回复，config.json 已配 8 条规则）≈ 尘锋的「AI质检识别违规话术/私单飞单」；chat-archive 的「证据化考核 base_score 100 + timeout/violation/filler 扣分」≈ 尘锋的质检扣分。**差异：chat-archive 是离线事后考核，尘锋是实时风控**。
- 可借鉴的商业模式: 「按坐席/人/年订阅 + 行业定制版高价」——chat-archive 可做行业规则包（如电商售后规则 vs 医美咨询规则）作为增值。

### 4. 探马 SCRM
- 官网: https://www.tanma.tech | 形态: 闭源商业产品（企微SCRM）
- 定位: 中大型企业企微SCRM，全套私域运营+客户管理
- 核心付费能力: 渠道活码、客户分层、在职/离职客户转移、话术库、朋友圈任务下发、**会话存档（永久留存文字/图片/语音/文件）+敏感词监控**
- 定价模式: 基础版 1080元/账号/年；标准版 1380元/账号/年（含会话存档服务版）；高级版 1680元/账号/年（含会话存档企业版）。来源：https://m.36dianping.com/vs/cnra.html ；http://news.xnnews.com.cn/cysx/202609/t20260930_5543357.shtml
- 目标客群: 有一定规模、需要会话存档合规的企业
- 与 chat-archive 能力的映射: chat-archive 的「convert_wx桥接 + SQLite+FTS5 全文检索 + 媒体归档 + 快照manifest」≈ 探马的「会话存档永久留存+时间/关键词搜索」。**差异：探马的存档是企微官方接口实时流，chat-archive 是事后导入导出文件——后者零合规门槛、零接口费**。
- 可借鉴的商业模式: 「会话存档是最大付费墙（比基础版贵 300-600元/账号/年）」——chat-archive 已自带"存档"（本地DB），可把它当成天然优势而非缺口。

### 5. 句客宝 / 句子互动
- 官网: https://www.36dianping.com/space/5979 | 形态: 闭源商业产品（企微SCRM + 私域RPA）
- 定位: 句客宝（企微客户管理）+ 句子秒回（自动回复），强调 API 打通与私域自动化
- 核心付费能力: 句子秒回自动回复、API 打通电话机器人/CRM、私有部署
- 定价模式: 句子秒回 2599元/年（按授权账号数，阶梯优惠）；私有部署（句客宝+句子秒回）20万元起，维护年费5万。来源：https://www.36dianping.com/space/5979
- 目标客群: 需要深度私域自动化、有技术能力打通系统的团队
- 与 chat-archive 能力的映射: chat-archive 不做"自动回复"（那是实时写入，合规风险高），但「FAQ 自动从群聊高频问题生成 + knowledge/training.jsonl」≈ 句子秒回的知识库底座。**差异：chat-archive 只做读/分析，不做写/回复，天然规避封号风险**。
- 可借鉴的商业模式: 「公有云按年授权 + 私有化一次性大额license」——chat-archive 作为纯本地CLI，私有化license模式非常契合（卖的就是"数据不出本机"）。

### 6. 晓多科技
- 官网: https://www.xiaoduoai.com | 形态: 闭源商业产品（电商垂直AI客服Agent）
- 定位: 电商智能客服Agent，覆盖淘宝/京东/抖音/拼多多售前售后
- 核心付费能力: 售前机器人、商品推荐、售后协同（青鸟）、**品牌舆情洞察Agent（识别投诉/差评/平台介入风险信号）**、客服模拟训练、SOP规则
- 定价模式: **按会话量计费 0.3元/会话**（含坐席许可，0起步）；零配置标准版 0.3万-3万/年；标准SaaS 2-4万/年；低代码 3万-10万/年。来源：https://www.xiaoduoai.com/active/gm2g4ms7 ；https://www.xiaoduoai.com/active/6250
- 目标客群: 电商卖家（单/多平台、5-50人客服团队）
- 与 chat-archive 能力的映射: **chat-archive 的 config.json `assessment.sop`（首响≤20s、问价后15min跟进、犹豫2min挽留、意向10min催拍）就是直接参考晓多的SOP规则表**；chat-archive 的「丢单/商机信号 + SLA分诊(P1紧急1h/P2 4h) + 质检信号四分类(Success/Frustration/Workflow/Request)」≈ 晓多的「舆情风险信号 + 售后场景识别」。**差异：晓多是实时接待机器人（替人回），chat-archive 是事后复盘（分析人回得好不好、哪些丢了）**。
- 可借鉴的商业模式: 「按效果/按会话计费，淡季不花钱旺季扩容」——chat-archive 可按"每次分析运行/每条商机信号"做轻量按量付费。

### 7. 网易七鱼
- 官网: https://www.163qiyukf.com | 形态: 闭源商业产品（智能客服SaaS）
- 定位: 在线客服+呼叫中心，网易系老牌客服云
- 核心付费能力: 在线客服工作台、智能机器人、工单、**实时/历史数据报表、数据大屏**、呼叫中心质检
- 定价模式: 在线客服 标准版 1888/坐席/年、专业版 3888/坐席/年、旗舰版 5888/坐席/年；呼叫中心 2999-5999/坐席/年；**数据大屏 28888/年**。来源：http://m.163qiyukf.com/channel/68.html ；https://www.36dianping.com/qa/5235.html
- 目标客群: 中小企业客服团队（教育/SaaS/电商）
- 与 chat-archive 能力的映射: chat-archive 的 `report.html`（19模块HTML看板）≈ 七鱼的「实时数据报表+数据大屏」。**差异：七鱼是实时在线客服看板（要接在线会话），chat-archive 是离线群聊归档看板（导入文件即出报告）**。
- 可借鉴的商业模式: 「数据大屏单独卖 28888/年」说明"可视化经营看板"本身是高价值付费点——chat-archive 的 report.html 可做成"群经营月报"订阅。

### 8. 智齿科技
- 官网: https://www.zhichi.com | 形态: 闭源商业产品（智能客服SaaS）
- 定位: 全场景客服一体化（在线+呼叫+机器人+工单）
- 核心付费能力: 文本机器人、智能外呼、呼入中心、CRM集成
- 定价模式: 基础版约 500-980元/月；标准版约 1980元/月；企业版 3980元/月起。来源：https://www.zhichi.com/news/4224.html ；https://www.zhichi.com/news/2381.html （注：智齿官网博客报价，非统一定价页，需以销售报价为准）
- 目标客群: 中大型企业客服中心
- 与 chat-archive 能力的映射: chat-archive 的「问题分级(P0投诉差评/P1退款赔偿/P2) + SLA分诊」≈ 智齿的工单优先级/智能路由思路。
- 可借鉴的商业模式: 「机器人/外呼/呼入分模块按月拆卖」——chat-archive 可按"模块"（考核包/商机包/知识库包）拆开订阅。

### 9. 美洽
- 官网: https://www.meiqia.com | 形态: 闭源商业产品（在线客服SaaS）
- 定位: 全渠道聚合在线客服，主打"不分版本全功能、按坐席收费"
- 核心付费能力: 全渠道聚合（抖音/小红书/官网/企微）、大模型获客机器人、智能打标签、实时数据看板
- 定价模式: 体验版 0元；专业版 1888/坐席/年；企业版 3888/坐席/年；旗舰版 5888/坐席/年。来源：https://m.36dianping.com/price/3002011121
- 目标客群: 中小型企业售前获客
- 与 chat-archive 能力的映射: chat-archive 的「@提及统计 + 昵称消歧 + profiles/*.md 客户画像」≈ 美洽的「智能打标签+客户来源追溯」。**差异：美洽靠在线会话埋点，chat-archive 靠群聊文本挖掘**。
- 可借鉴的商业模式: 「全功能不分版本、只按坐席分档」——极简定价，适合 chat-archive 做"单一年费、功能全开放"的引流款。

### 10. Dify
- 官网: https://dify.ai | 形态: 开源产品（自托管免费）+ 闭源商业云版
- 定位: LLM 应用开发平台（RAG/Agent/工作流），开源标杆
- 核心付费能力: 云端托管、消息额度(message credits)、团队协作、知识库文档量、API限流、企业SSO
- 定价模式: Sandbox 免费（200 credits/月）；Professional $59/月（$590/年，5000 credits/月、3成员、500文档）；Team $159/月（$1590/年，10000 credits/月、50成员）；Enterprise 定制。**自托管社区版完全免费**。来源：https://dify.ai/pricing ；https://www.aiwiki.ai/wiki/dify
- 目标客群: 开发者/AI团队构建生产级AI应用
- 与 chat-archive 能力的映射: chat-archive 的「LLM提炼(OpenAI兼容) + chroma向量检索(可选) + ima知识库对接」本质上是一个垂直版的RAG管道，但**chat-archive 不做通用agent编排，只做"群聊→结构化报告"这一条垂直流水线**。
- 可借鉴的商业模式: 「核心自托管免费 + 云托管按workspace年付+消息额度」——chat-archive 可坚持本地免费、卖"托管版/云报告推送"或"额度包"。

### 11. FastGPT
- 官网: https://doc.fastgpt.io | 形态: 开源产品 + 闭源商业授权
- 定位: 国产RAG知识库问答平台，主打知识库质量
- 核心付费能力: 商业授权（可商用）、SSO/RBAC/多租户/审计日志、优先工单、Sealos全托管
- 定价模式: 商业版按部署方式分；**Sealos 全托管 ¥10,000/月起（最低3个月）或 ¥120,000/年**（8C32G资源）；私有部署按服务器license分标准/专业/旗舰。来源：https://doc.fastgpt.io/en/introduction/commercial
- 目标客群: 需要私有化部署知识库问答的企业
- 与 chat-archive 能力的映射: chat-archive 的「knowledge/ + training.jsonl + onboarding.md + FTS5检索」≈ FastGPT 的知识库构建，但 chat-archive 聚焦群聊语料的自动清洗。
- 可借鉴的商业模式: 「开源版免费、商用授权按年/按服务器license收费」——这是 chat-archive 若走开源路线最直接的对标：个人随便用，商用/企业部署要授权费。

### 12. Intercom Fin
- 官网: https://www.intercom.com/pricing | 形态: 闭源商业产品（海外客服平台+AI Agent）
- 定位: 下一代客服台 + Fin AI Agent，行业标杆
- 核心付费能力: Fin AI Agent 自动解决工单、Helpdesk、Messenger、数据看板
- 定价模式: 坐席 Essential $29/seat/月（年付，月付$39）、Advanced $85/seat/月（$99）、Expert $132/seat/月（$139）；**Fin AI Agent 按结果计费 $0.99/次成功解决(resolution)**。来源：https://www.intercom.com/help/en/articles/9061614-intercom-plans-explained ；https://go.chargebee.com/.../chargebee_state_of_recurring_revenue_and_monetization_report.pdf
- 目标客群: 海外中大型SaaS/科技企业
- 与 chat-archive 能力的映射: Fin 的 $0.99/resolution 是"按AI产出结果付费"的标杆——chat-archive 的「每条丢单信号/每条商机信号/每份日报」天然可按"产出物"计费，而非按人头。
- 可借鉴的商业模式: 「按AI解决结果付费(outcome-based)，不解决不收钱」——chat-archive 的"商机信号命中数"可做效果付费锚点。

### 13. Chatbase
- 官网: https://www.chatbase.co | 形态: 闭源商业产品（AI聊天机器人搭建）
- 定位: 几分钟训练一个网站/文档问答bot，无需代码
- 核心付费能力: 上传文档/网站训练bot、消息额度、多bot、AI Actions
- 定价模式: Free（50 credits/月，14天不活跃删bot）；Hobby $40/月（~2000 credits）；Standard $150/月（4000 credits）；Pro $500/月（15000 credits）；Enterprise定制。来源：https://letsmetrix.com/app/chatbase/pricing ；https://www.chatbase.co/blog/livechat-alternatives
- 目标客群: 中小企业/创业者做客服bot/内部问答
- 与 chat-archive 能力的映射: chat-archive 自动从群聊生成 FAQ + training.jsonl ≈ Chatbase 的"上传文档训练bot"的上游语料生产环节。
- 可借鉴的商业模式: 「免费额度引流 + 按消息额度分档订阅」——chat-archive 可做"每月N次免费分析，超出订阅"。

### 14. Notion AI
- 官网: https://www.notion.com/product/ai | 形态: 闭源商业产品（协作笔记+AI）
- 定位: All-in-one 工作区，AI 内置为 workspace tier
- 核心付费能力: Business版含完整AI（Ask Notion/AI Agents/数据库自动填充/连接器）
- 定价模式: Free/Plus 仅一次性20次试用；**Business $20/member/月（年付）含完整AI**；Enterprise定制。来源：https://www.notion.com/product/ai?lang=en ；https://www.usagepricing.com/blueprint/notion-ai
- 目标客群: 团队/知识工作者
- 与 chat-archive 能力的映射: Notion 把AI"打包进席位套餐"而非单独卖——chat-archive 可参考"本地版免费，团队协作/报告推送作为高级tier"。
- 可借鉴的商业模式: 「AI 不再单独卖，而是包进更高席位套餐」——暗示纯AI功能单独卖正在变难，要和协作/沉淀绑定。

### 15. 快团团
- 官网: https://ktt.pinduoduo.com | 形态: 闭源商业产品（拼多多旗下社群团购工具）
- 定位: 微信私域卖货小程序，0门槛开团/帮卖分销
- 核心付费能力: 开团/跟团/帮卖分销、团主页涨粉、粉丝群裂变、分享返佣（工具本身免费，靠交易抽成/导流变现）
- 定价模式: **工具完全免费**，微信支付通道费0.6%（官方补贴0.3%），无入驻费/保证金。来源：https://ktt.pinduoduo.com/login ；https://www.fxmsoft.com/gs/show_2054.html
- 目标客群: 社区团购团长/宝妈/小商家
- 与 chat-archive 能力的映射: 快团团免费工具靠"交易流水"变现——chat-archive 不碰交易，但可参考"工具免费聚用户，在高价值分析环节收费"。
- 可借鉴的商业模式: 「工具免费、生态抽成」——chat-archive 的差异化恰恰是不碰交易（规避合规），所以不能照抄抽成，但"免费归档+付费深度报告"可借鉴。

### 16. 群接龙
- 官网: https://www.qunjielong.com | 形态: 闭源商业产品（社群团购/接龙工具）
- 定位: 微信社群接龙卖货，比快团团更私密
- 核心付费能力: 接龙交易、付费主页（社群/团长/品牌主页）、帮卖体系
- 定价模式: **每笔接龙交易收 1% 服务费**（充值时扣）；提现0.5元/笔；帮卖团长主页 299元/年、选品团长主页 599元/年、品牌主页 999元/年。来源：https://helpme.qunjielong.com/10b2/8ad0/ ；https://hao.qunjielong.com/ef93/6583/
- 目标客群: 团长/品牌供货商
- 与 chat-archive 能力的映射: 群接龙"基础接龙免费、主页装扮按年订阅"——chat-archive 可把"基础归档报告免费、高级看板/品牌化报告按年订阅"。
- 可借鉴的商业模式: 「交易抽成 + 轻量主页年费」双轮——chat-archive 不抽交易，但可做"高级报告模板/品牌化"年费。

### 17. 小鹅通
- 官网: https://www.xiaoe-tech.com/server_price | 形态: 闭源商业产品（知识店铺/私域变现SaaS）
- 定位: 微信内内容付费/卖课/直播/私域经营店铺
- 核心付费能力: 店铺搭建、直播带货、专栏课程、会员体系、AI点、CRM精细化运营
- 定价模式: AI基础版 6800元/年；AI专业版 12800元/年；AI旗舰版 25800元/年（赠存储/流量/席位/AI点）。来源：https://www.xiaoe-tech.com/server_price/ ；https://sem.xiaoe-tech.com/moreNews/articleDetail-5847.html
- 目标客群: 知识付费老师/培训机构/品牌私域
- 与 chat-archive 能力的映射: 小鹅通卖"私域变现店铺"，chat-archive 是"私域群聊分析"——一个管交付/交易，一个管复盘/洞察。
- 可借鉴的商业模式: 「三档年订阅 + 每档赠AI点/存储/流量」——chat-archive 可做"年订阅赠N次LLM提炼额度"。

### 18. 知识星球
- 官网: https://www.zsxqq.com | 形态: 闭源商业产品（付费社群/圈子）
- 定位: 付费主题社群，星主运营圈子、用户按年付费加入
- 核心付费能力: 付费加入星球、付费提问、赞赏、礼品卡
- 定价模式: **不收年费，抽交易分成**——个人星球阶梯 20%（年收入≤10万）/10%（>10万部分）；企业星球 10%（≤10万）/5%（>10万）；iOS苹果内购另抽25%+2%税。来源：https://doc.zsxq.com/personal_expense_adjustments.html ；https://doc.zsxq.com/announcement/feilvtiaozhengtongzhi.html
- 目标客群: 知识型星主/垂直社群运营者
- 与 chat-archive 能力的映射: 知识星球靠"社群活跃度/内容沉淀"留住付费用户——chat-archive 的「群活跃度+讨论摘要+知识库归档」正是帮星主证明"这个群值回票价"的后台。
- 可借鉴的商业模式: 「平台抽成而非卖license」——chat-archive 若做SaaS，可对"通过分析促成的增值服务"抽成，但早期不宜，先卖订阅。

### 19. Echobase
- 官网: https://echobase.ai/pricing | 形态: 闭源商业产品（企业数据AI问答/知识库）
- 定位: 把企业内部数据（PDF/DB/CSV）喂给AI，让AI Agent基于自有数据回答
- 核心付费能力: 上传数据建库、AI查询、多Agent、团队协作
- 定价模式: Free（20 queries/月、20页、1 agent）；Individual $19/月（2100 queries）；Professional $49/月（6500 queries）；Enterprise $299/月（25000 queries、20 agents、5席位）。来源：https://echobase.ai/pricing ；https://creati.ai/tag/...
- 目标客群: 企业数据团队/想基于内部数据做AI问答的公司
- 与 chat-archive 能力的映射: Echobase 是"上传企业数据→AI问答"，chat-archive 是"上传群聊→结构化洞察+知识库"。**差异：Echobase 要你自己整理数据上传，chat-archive 自动从群聊原始记录清洗出结构化洞察**。
- 可借鉴的商业模式: 「按查询queries额度分档」——chat-archive 的 LLM 提炼次数可类比 queries 额度。

### 20. Throngwatch（海外Discord聊天分析，最贴近 chat-archive 形态）
- 官网: https://throngwatch.com | 形态: 闭源商业产品（社区聊天AI分析）
- 定位: "Read your Discord without reading it"——AI批量消化Discord消息，输出社区洞察
- 核心付费能力: 信用点(credit)制AI分析，1 credit ≈ 分析1000条消息；无需逐条读群
- 定价模式: 注册送3 credit；之后 credit 包 $2/credit（付费计划低至$1/credit）；**订阅计划$7/月起**（含credit，年付省20%）。来源：https://throngwatch.com
- 目标客群: Discord/Slack海外社区运营、Web3社群管理者
- 与 chat-archive 能力的映射: **这是全调研中与 chat-archive 形态最像的产品**——都是"把海量聊天记录交给AI批量消化、输出洞察、免去人工逐条读"。chat-archive 的「按时段压缩 + 四分类摘要 + 讨论摘要 + 日报」≈ Throngwatch 的 credit-based AI digest。**差异：Throngwatch 接Discord实时API，chat-archive 吃微信/QQ导出文件；Throngwatch $7/月起极轻量**。
- 可借鉴的商业模式: **「$7/月起轻订阅 + credit按量」正是 chat-archive 应走的路——低门槛月费+按分析消息量/credit加购**。

---

## 二、商业化方向建议（本组重点交付）

> 按"差异化卖点强度"排序。chat-archive 的根本差异化：**纯本地CLI、零企微接口合规门槛、吃导出文件（个人微信群/QQ群也能分析，SCRM吃不到这块）、电商垂直洞察内置、数据不出本机**。

### 方向1：丢单/商机信号雷达 —— 按"命中信号数"效果付费
- **能力组合**: 现有「丢单/商机信号 + SLA分诊(P1紧急1h) + 跟进清单 + @提及统计」+ 待加：每日/每群"未回复客户提问"推送（微信/邮件/webhook）
- **目标客群**: 电商中小卖家、社群团购团长、有多个客群的私域运营（管5-50个群、客服2-10人）
- **收费模式建议**: 免费版每天出一次report.html；**付费版按"商机信号命中数"包月**（如 49元/月含100条信号命中，超出0.5元/条），对标晓多0.3元/会话、Intercom $0.99/resolution
- **为什么有差异化**: SCRM（微伴/尘锋/探马）的会话质检要企微官方存档接口+企业认证，**个人微信群/QQ群根本接不进去**；chat-archive 吃导出文件，天然覆盖这批SCRM吃不到的"野生群主"。而且SCRM的质检聚焦"员工合规"，chat-archive 聚焦"客户有没有人跟、会不会丢单"——这是老板最肉疼的钱。
- **竞品对标**: 晓多科技舆情/丢单信号（但它是实时接待机器人，贵）、探马会话存档（但要企微接口）、Throngwatch（$7/月，但只接Discord）

### 方向2：本地/私有化"会话存档+质检"——卖数据不出本机
- **能力组合**: 现有「SQLite+FTS5全文检索 + 证据化考核(base_score+超时/违规扣分) + 质检信号四分类 + 8条合规规则 + 媒体归档 + 快照manifest」+ 待加：多员工考核对比导出、按规则自定义扣分表GUI
- **目标客群**: 对数据敏感的行业——医美/口腔/律所/金融/高客单电商（尘锋深耕的行业，恰恰也是最怕聊天记录上云的行业）
- **收费模式建议**: **个人/小团队永久免费版；企业私有化license 一次性 3000-8000元/年**（对标句客宝私有部署20万起，chat-archive 走轻量），按群数/员工数分档
- **为什么有差异化**: 尘锋/探马/微伴都是SaaS，聊天记录要上他们云；chat-archive 纯本地Python，**数据一个字节不出本机**，这对医美/金融/高客单是硬刚需（合规+客户隐私）。纯标准库+Windows/macOS双端，部署成本极低。
- **竞品对标**: 尘锋私有定制20万起、句客宝私有部署20万起、FastGPT商用授权¥10万+/年——chat-archive 用"轻量本地license"打性价比空档

### 方向3：客服团队月度质检报告订阅——轻量SaaS化看板
- **能力组合**: 现有「客服考核(证据化) + 有效回复统计 + 群活跃度 + SOP合规(首响20s/问价15min跟进) + 讨论摘要 + 日报」+ 待加：多群汇总月报PDF/HTML、员工排名导出、邮件自动推送
- **目标客群**: 电商客服主管、私域运营负责人（要给老板交差、要考核客服绩效的人）
- **收费模式建议**: **按"群数+月"订阅，99元/群/月起，或 599元/月含10群**（对标七鱼数据大屏28888/年、微伴会话扩展包300元/账号/年——chat-archive 按群不按人头，小团队更省）
- **为什么有差异化**: 七鱼/美洽/智齿的报表绑定在在线客服工作台里（你得先用他们的客服系统）；chat-archive **不替换你的客服系统，只对已有群聊记录做赛后复盘**，不侵入现有工作流。
- **竞品对标**: 网易七鱼数据大屏28888/年、微伴群聊质检扩展包、尘锋AI质检

### 方向4：群聊→可搜索知识库（onboarding/新人培训）——企业知识沉淀
- **能力组合**: 现有「knowledge/自动归档 + training.jsonl + onboarding.md + FAQ自动生成 + ima对接 + chroma向量检索(可选) + 昵称消歧」+ 待加：知识库质量评分、定期知识更新提醒
- **目标客群**: 有大量客服群/技术支持群的团队（新人入职要翻历史群聊找答案）、电商卖家（把高频问题沉淀成FAQ）
- **收费模式建议**: **知识库模块作为高级版解锁**（含在方向2/3的付费档里，或单独 199元/月）；可对接 ima/Notion 作为增值导出
- **为什么有差异化**: Dify/FastGPT/Chatbase 要你手动上传文档建知识库；chat-archive **自动从日常群聊里沉淀FAQ和onboarding手册，零额外录入**——群聊天天产生，知识库自动长出来。
- **竞品对标**: Dify $59/月、FastGPT商用¥10万/年、Chatbase $40/月——都是通用RAG，chat-archive 是"群聊语料自动治理"垂直入口

### 方向5：需求洞察/产品反馈月报——给产品/运营的VOC
- **能力组合**: 现有「需求洞察(规则聚类客户痛点) + 关键词趋势 + 问题分级(P0投诉差评/P1退款赔偿) + 话题分类(发货/退款/发票/库存/质量)」+ 待加：跨月痛点趋势对比、差评归因
- **目标客群**: 电商产品经理、选品负责人、社群运营（想知道客户在抱怨什么、想要什么）
- **收费模式建议**: **作为方向3月报的高级模块，或单独 299元/月/品牌**（对标晓多品牌舆情洞察Agent，按品牌单独报价）
- **为什么有差异化**: 晓多舆情Agent绑定实时电商客服会话（淘宝/京东）；chat-archive 分析的是**微信群里的非正式抱怨**——这些抱怨不会出现在电商平台评价里，却是真实的产品改进信号，竞品拿不到。
- **竞品对标**: 晓多品牌舆情洞察Agent（价格未公开，按品牌报价）

### 方向6：LLM提炼额度包——算力转售/credit
- **能力组合**: 现有「LLM提炼(OpenAI兼容,DeepSeek) + 按时段压缩省token + 证据化溯源标注」+ 待加：用量统计面板、credit充值
- **目标客群**: 所有付费用户（LLM提炼是体验提升最大的开关）
- **收费模式建议**: **基础规则版免费（纯标准库heuristic），AI提炼走credit包**（如 39元/月含50万token，对标ima算力制、Dify message credits）
- **为什么有差异化**: chat-archive 已有"按时段压缩"专门省token——单位分析成本比裸调LLM低，credit包毛利率可控。
- **竞品对标**: 腾讯ima算力制、Dify message credits、Chatbase message credits

### 方向7：年度经营复盘报告——一次性高客单
- **能力组合**: 现有「年度分析 + 关键词趋势 + 活跃度年度汇总 + 客户/员工画像跨年对比」
- **目标客群**: 年底要做复盘的老板/运营负责人
- **收费模式建议**: **一次性 999-2999元/份**（人工解读+AI分析，对标七鱼数据大屏28888/年、小鹅通6800/年）
- **为什么有差异化**: 年度复盘需要跨12个月数据，chat-archive 的增量处理+记忆层天然支持，竞品SCRM的年报往往要高阶版本才给。
- **竞品对标**: 小鹅通版本年费、七鱼集团版定制

### 方向8：行业规则包/模板——垂直深耕
- **能力组合**: 现有「topics话题规则 + assessment.rules合规规则 + SLA分诊阈值」全部配置化（config.json改规则不改代码）+ 待加：电商售后/医美咨询/教培/装修 等行业规则包一键切换
- **目标客群**: 特定行业的中小团队
- **收费模式建议**: **基础规则免费，行业规则包 99-199元/包**（对标尘锋按行业深耕30+行业、晓多按类目定制训练）
- **为什么有差异化**: config.json 已证明规则可配置，做行业包边际成本极低；SCRM的行业方案要几万块，chat-archive 卖几十块的"规则模板"。
- **竞品对标**: 尘锋行业方案、晓多类目定制训练

---

## 三、可吸收能力建议（本组）

| 能力 | 来源产品 | chat-archive现状缺口 | 实施成本 | 商业化价值 | 交互增益 | 是否需新依赖 |
|---|---|---|---|---|---|---|
| 每日/每群"未回复客户提问"webhook/邮件推送 | 晓多丢单信号、Throngwatch | 现有report.html是离线文件，无主动触达 | 中 | **高**（方向1核心，老板要"主动收到"） | 高：从"跑完看文件"变"推送提醒" | 否（SMTP/企业微信webhook标准库可发） |
| 多群汇总月报（PDF/HTML）+员工排名导出 | 七鱼数据大屏、微伴成员统计 | 现有report是单次/单群，缺跨群汇总月报 | 中 | **高**（方向3核心付费物） | 高：直接交付给老板看的成品 | 否（HTML已有，PDF可选weasyprint） |
| 按credit/命中数计费的额度系统+用量面板 | ima算力、Dify credits、Throngwatch | 无任何用量计量 | 中 | 中（方向6，需SaaS化后才用得上） | 中：商业化基础设施 | 否 |
| 知识库质量评分+知识更新提醒 | FastGPT知识库、Echobase | knowledge/只生成不评分 | 低 | 中（方向4） | 中：告诉用户"知识库里哪些过时了" | 否 |
| 跨月痛点趋势对比（VOC时序） | 晓多舆情洞察 | 现有关键词趋势是单次，缺跨月对比 | 中 | 中（方向5） | 中：产品经理要"环比" | 否（已有history.json锚点，扩展即可） |
| 行业规则包一键切换（电商/医美/教培） | 尘锋行业方案、晓多类目 | config规则已可配，但无预置行业包 | 低 | 中（方向8） | 低：配置便利 | 否 |
| report.html长图分享（已有screenshot开关） | 七鱼数据大屏、知识星球分享 | 已有playwright截图开关，默认关 | 低 | 低 | 高：手机里直接转发给老板看 | 是（playwright，已有开关） |
| SOP合规实时提醒（命中即记录已有，缺推送） | 微伴群SOP、尘锋智能SOP | sop_compliance已记录，但无即时提醒 | 中 | 中 | 高：客服问价15min没跟，立刻提醒 | 否 |
| 客户画像自动累积（profiles已有，缺客户维度聚合） | 美洽智能打标签、尘锋AI客户画像 | 现有profiles是员工/客户发言画像，缺"按客户聚合的历史" | 中 | 中 | 高：新客服接手能翻这个客户历史 | 否（SQLite已有） |
| 问答bot层（把knowledge/接成可对话的bot） | Chatbase、Dify、FastGPT | 现有只生成FAQ/training.jsonl，缺可对话接口 | 高 | 中高 | 高：从"看报告"到"直接问群聊" | 是（但可走ima API，已有对接） |

---

## 四、排除项（本组）

| 产品/模式 | 排除原因 |
|---|---|
| 快团团/群接龙的交易抽成模式 | chat-archive 定位是"分析/归档"，不碰交易链路；接支付/订单既重又触碰平台合规红线，与"纯标准库、稳定第一"约束冲突 |
| 实时自动回复/替人回消息（句子秒回、晓多机器人、美洽获客bot） | 实时写入微信消息=高封号风险+合规风险，chat-archive 明确做"读/分析"不做"写/回复"，这是产品红线不应碰 |
| 企微官方会话存档接口对接（微伴/尘锋/探马的核心） | 需要企业认证+企微接口费（约5920元/年/100人）+合规审批，与chat-archive"吃导出文件、零门槛"的差异化定位冲突；做了反而和SCRM正面拼资源 |
| 呼叫中心/电话外呼（七鱼/智齿/容联） | 完全偏离群聊归档场景，硬件/线路/资质重 |
| 全渠道在线客服工作台（七鱼/美洽/智齿/Intercom） | 那是替换客服系统的重SaaS，chat-archive 是"赛后复盘"，定位不同，正面做必败 |
| 商城/卖课/知识店铺（小鹅通、知识星球交易） | chat-archive 不做交付/交易载体，只做分析层 |
| 通用LLM agent编排平台（Dify/FastGPT全量） | chat-archive 不做通用bot搭建，只做"群聊→结构化报告"这一条垂直流水线，做通用平台是扬短避长 |
| 按坐席人头收费的SCRM模式（尘锋1200/人/年） | chat-archive 是按群/按产出物分析，不是按人头管理员工，按人头收会把小群主挡在门外 |

---

## 五、核心结论（一句话版）

1. **最有想象力：丢单/商机信号雷达**——SCRM吃不到个人微信群，chat-archive 吃导出文件无合规门槛，按"命中信号数"效果付费，正中老板"客户没人跟=丢钱"的痛点。
2. **最稳：本地私有化质检license**——数据不出本机是医美/金融/高客单的硬刚需，纯本地CLI天然适配，打SaaS上云产品的差异化空档。
3. **最轻量起量：月度质检/经营报告订阅**——按群不按人头（99元/群/月起），不替换现有客服系统，只做赛后复盘。
4. **最高杠杆：群聊→知识库自动沉淀**——Dify/Chatbase 要人手动传文档，chat-archive 让知识库从群聊里自动长出来。
5. **计费范式：学Throngwatch+Intercom**——$7/月轻订阅引流 + credit/按产出物（信号数/分析条数）加购，而非按人头坐席。
