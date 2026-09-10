-- 禾诊 MySQL 初始化脚本
-- 来源：禾诊_SQL数据库架构图.pptx；6 张核心表、8 条外键。
-- 适用 MySQL 8.0.16+（需要实际执行 CHECK 约束），UTF-8。
-- 图中仅列关键字段；补充现有诊断接口所需快照、来源与时间字段。
-- 新库初始化使用；已有同名但结构不同的表不会自动升级。
-- 不删除数据库或旧 diagnosis_records；不预置账户或明文密码。
-- DDL 会隐式提交。先备份已有库，再执行；不要使用忽略错误的 --force。
SET NAMES utf8mb4;
SET @HEZHEN_OLD_SQL_MODE = @@SESSION.sql_mode;
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION,NO_BACKSLASH_ESCAPES';
CREATE DATABASE IF NOT EXISTS hezhen_db CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
USE hezhen_db;


CREATE TABLE IF NOT EXISTS crops (
	id BIGINT NOT NULL AUTO_INCREMENT,
	crop_key VARCHAR(80) NOT NULL,
	name_zh VARCHAR(80) NOT NULL,
	status VARCHAR(20) NOT NULL DEFAULT 'active',
	sort_order INTEGER NOT NULL DEFAULT '0',
	PRIMARY KEY (id),
	CONSTRAINT ck_crops_status CHECK (status IN ('active', 'disabled')),
	UNIQUE (crop_key)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS users (
	id BIGINT NOT NULL AUTO_INCREMENT,
	username VARCHAR(80) NOT NULL,
	email VARCHAR(254),
	password_hash VARCHAR(255) NOT NULL,
	`role` VARCHAR(20) NOT NULL DEFAULT 'user',
	status VARCHAR(20) NOT NULL DEFAULT 'active',
	created_at DATETIME NOT NULL DEFAULT now(),
	PRIMARY KEY (id),
	CONSTRAINT ck_users_role CHECK (role IN ('user', 'admin')),
	CONSTRAINT ck_users_status CHECK (status IN ('active', 'disabled')),
	UNIQUE (username),
	UNIQUE (email)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS diseases (
	id BIGINT NOT NULL AUTO_INCREMENT,
	crop_id BIGINT NOT NULL,
	model_class_index INTEGER NOT NULL,
	model_label VARCHAR(255) NOT NULL,
	name_zh VARCHAR(120) NOT NULL,
	category VARCHAR(20) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_diseases_class_index CHECK (model_class_index >= 0),
	FOREIGN KEY(crop_id) REFERENCES crops (id) ON DELETE RESTRICT,
	UNIQUE (model_class_index),
	UNIQUE (model_label),
	INDEX ix_diseases_crop_id (crop_id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS diagnosis_history (
	id VARCHAR(36) NOT NULL,
	user_id BIGINT,
	crop_id BIGINT NOT NULL,
	disease_id BIGINT NOT NULL,
	client_id VARCHAR(36),
	crop VARCHAR(80) NOT NULL,
	crop_zh VARCHAR(80) NOT NULL,
	symptom_description VARCHAR(1000),
	original_filename VARCHAR(255) NOT NULL,
	image_url VARCHAR(1000),
	model_label VARCHAR(255) NOT NULL,
	disease_zh VARCHAR(120) NOT NULL,
	confidence NUMERIC(8, 6) NOT NULL,
	decision VARCHAR(40) NOT NULL,
	diagnosis_json JSON NOT NULL,
	advice_json JSON NOT NULL,
	report_text TEXT NOT NULL,
	created_at DATETIME NOT NULL DEFAULT now(),
	PRIMARY KEY (id),
	CONSTRAINT ck_history_owner CHECK (user_id IS NOT NULL OR (client_id IS NOT NULL AND length(trim(client_id)) > 0)),
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(crop_id) REFERENCES crops (id) ON DELETE RESTRICT,
	FOREIGN KEY(disease_id) REFERENCES diseases (id) ON DELETE RESTRICT,
	INDEX idx_diagnosis_client_created (client_id, created_at),
	INDEX idx_diagnosis_crop_created (crop, created_at),
	INDEX idx_diagnosis_label_created (model_label, created_at),
	INDEX idx_diagnosis_user_created (user_id, created_at),
	INDEX ix_diagnosis_history_crop_id (crop_id),
	INDEX ix_diagnosis_history_disease_id (disease_id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS knowledge_base (
	id BIGINT NOT NULL AUTO_INCREMENT,
	disease_id BIGINT NOT NULL,
	source_code VARCHAR(100) NOT NULL,
	title VARCHAR(200) NOT NULL,
	content MEDIUMTEXT NOT NULL,
	tags JSON,
	source_org VARCHAR(200) NOT NULL,
	source_url VARCHAR(2048) NOT NULL,
	source_updated VARCHAR(100) NOT NULL DEFAULT '',
	created_at DATETIME NOT NULL DEFAULT now(),
	updated_at DATETIME NOT NULL DEFAULT now(),
	PRIMARY KEY (id),
	FOREIGN KEY(disease_id) REFERENCES diseases (id) ON DELETE RESTRICT,
	UNIQUE (source_code),
	INDEX ix_knowledge_base_disease_id (disease_id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS diagnosis_feedback (
	id BIGINT NOT NULL AUTO_INCREMENT,
	history_id VARCHAR(36) NOT NULL,
	user_id BIGINT,
	corrected_disease_id BIGINT,
	client_id VARCHAR(36),
	is_correct BOOL NOT NULL,
	content VARCHAR(2000),
	created_at DATETIME NOT NULL DEFAULT now(),
	PRIMARY KEY (id),
	CONSTRAINT ck_feedback_owner CHECK (user_id IS NOT NULL OR (client_id IS NOT NULL AND length(trim(client_id)) > 0)),
	CONSTRAINT ck_feedback_correct CHECK (is_correct IN (0, 1)),
	UNIQUE (history_id),
	FOREIGN KEY(history_id) REFERENCES diagnosis_history (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(corrected_disease_id) REFERENCES diseases (id) ON DELETE RESTRICT,
	INDEX ix_diagnosis_feedback_corrected_disease_id (corrected_disease_id),
	INDEX ix_diagnosis_feedback_user_id (user_id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;


-- 初始作物、38 个模型标签与已有知识条目；通过自然键定位外键，不覆盖已存在内容。
START TRANSACTION;

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Apple', '苹果', 'active', 0 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Apple');

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Blueberry', '蓝莓', 'active', 1 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Blueberry');

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Cherry_(including_sour)', '樱桃', 'active', 2 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Cherry_(including_sour)');

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Corn_(maize)', '玉米', 'active', 3 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Corn_(maize)');

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Grape', '葡萄', 'active', 4 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Grape');

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Orange', '柑橘', 'active', 5 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Orange');

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Peach', '桃', 'active', 6 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Peach');

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Pepper,_bell', '甜椒', 'active', 7 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Pepper,_bell');

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Potato', '马铃薯', 'active', 8 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Potato');

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Raspberry', '树莓', 'active', 9 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Raspberry');

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Soybean', '大豆', 'active', 10 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Soybean');

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Squash', '南瓜', 'active', 11 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Squash');

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Strawberry', '草莓', 'active', 12 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Strawberry');

INSERT INTO crops (crop_key, name_zh, status, sort_order) SELECT 'Tomato', '番茄', 'active', 13 WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = 'Tomato');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Apple'), 0, 'Apple___Apple_scab', '苹果黑星病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Apple___Apple_scab');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Apple'), 1, 'Apple___Black_rot', '黑腐病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Apple___Black_rot');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Apple'), 2, 'Apple___Cedar_apple_rust', '雪松苹果锈病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Apple___Cedar_apple_rust');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Apple'), 3, 'Apple___healthy', '健康', 'healthy' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Apple___healthy');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Blueberry'), 4, 'Blueberry___healthy', '健康', 'healthy' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Blueberry___healthy');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Cherry_(including_sour)'), 5, 'Cherry_(including_sour)___Powdery_mildew', '白粉病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Cherry_(including_sour)___Powdery_mildew');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Cherry_(including_sour)'), 6, 'Cherry_(including_sour)___healthy', '健康', 'healthy' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Cherry_(including_sour)___healthy');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Corn_(maize)'), 7, 'Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot', '灰斑病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Corn_(maize)'), 8, 'Corn_(maize)___Common_rust_', '普通锈病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Corn_(maize)___Common_rust_');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Corn_(maize)'), 9, 'Corn_(maize)___Northern_Leaf_Blight', '北方叶枯病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Corn_(maize)___Northern_Leaf_Blight');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Corn_(maize)'), 10, 'Corn_(maize)___healthy', '健康', 'healthy' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Corn_(maize)___healthy');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Grape'), 11, 'Grape___Black_rot', '黑腐病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Grape___Black_rot');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Grape'), 12, 'Grape___Esca_(Black_Measles)', '黑麻疹病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Grape___Esca_(Black_Measles)');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Grape'), 13, 'Grape___Leaf_blight_(Isariopsis_Leaf_Spot)', '叶枯病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Grape___Leaf_blight_(Isariopsis_Leaf_Spot)');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Grape'), 14, 'Grape___healthy', '健康', 'healthy' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Grape___healthy');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Orange'), 15, 'Orange___Haunglongbing_(Citrus_greening)', '黄龙病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Orange___Haunglongbing_(Citrus_greening)');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Peach'), 16, 'Peach___Bacterial_spot', '细菌性斑点病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Peach___Bacterial_spot');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Peach'), 17, 'Peach___healthy', '健康', 'healthy' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Peach___healthy');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Pepper,_bell'), 18, 'Pepper,_bell___Bacterial_spot', '细菌性斑点病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Pepper,_bell___Bacterial_spot');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Pepper,_bell'), 19, 'Pepper,_bell___healthy', '健康', 'healthy' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Pepper,_bell___healthy');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Potato'), 20, 'Potato___Early_blight', '早疫病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Potato___Early_blight');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Potato'), 21, 'Potato___Late_blight', '晚疫病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Potato___Late_blight');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Potato'), 22, 'Potato___healthy', '健康', 'healthy' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Potato___healthy');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Raspberry'), 23, 'Raspberry___healthy', '健康', 'healthy' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Raspberry___healthy');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Soybean'), 24, 'Soybean___healthy', '健康', 'healthy' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Soybean___healthy');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Squash'), 25, 'Squash___Powdery_mildew', '白粉病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Squash___Powdery_mildew');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Strawberry'), 26, 'Strawberry___Leaf_scorch', '叶焦病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Strawberry___Leaf_scorch');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Strawberry'), 27, 'Strawberry___healthy', '健康', 'healthy' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Strawberry___healthy');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Tomato'), 28, 'Tomato___Bacterial_spot', '细菌性斑点病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Tomato___Bacterial_spot');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Tomato'), 29, 'Tomato___Early_blight', '早疫病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Tomato___Early_blight');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Tomato'), 30, 'Tomato___Late_blight', '晚疫病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Tomato___Late_blight');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Tomato'), 31, 'Tomato___Leaf_Mold', '叶霉病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Tomato___Leaf_Mold');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Tomato'), 32, 'Tomato___Septoria_leaf_spot', '斑枯病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Tomato___Septoria_leaf_spot');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Tomato'), 33, 'Tomato___Spider_mites Two-spotted_spider_mite', '二斑叶螨', 'pest' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Tomato___Spider_mites Two-spotted_spider_mite');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Tomato'), 34, 'Tomato___Target_Spot', '靶斑病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Tomato___Target_Spot');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Tomato'), 35, 'Tomato___Tomato_Yellow_Leaf_Curl_Virus', '黄化曲叶病毒病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Tomato___Tomato_Yellow_Leaf_Curl_Virus');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Tomato'), 36, 'Tomato___Tomato_mosaic_virus', '花叶病毒病', 'disease' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Tomato___Tomato_mosaic_virus');

INSERT INTO diseases (crop_id, model_class_index, model_label, name_zh, category) SELECT (SELECT id FROM crops WHERE crop_key = 'Tomato'), 37, 'Tomato___healthy', '健康', 'healthy' WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = 'Tomato___healthy');

INSERT INTO knowledge_base (disease_id, source_code, title, content, tags, source_org, source_url, source_updated) SELECT (SELECT id FROM diseases WHERE model_label = 'Tomato___Bacterial_spot'), 'KB-TOMATO-BACTERIAL-SPOT-001', '番茄细菌性斑点病：识别与田间管理', '番茄细菌性斑点病可影响叶、茎、叶柄和果实。叶片常见细小褐色圆斑及黄色晕圈，斑点中心可能脱落形成小孔；与早疫病相比，通常不呈明显同心轮纹。温暖潮湿、叶面长时间湿润时风险增大，雨水或喷灌飞溅、操作人员双手和工具都可能传播病原。在等待专业复核期间，可清除症状明显的叶片并与健康植株隔离，避免植株湿润时进行整枝或接触，改用根部浇水或滴灌，清洁消毒接触过病株的工具。后续应选用健康种苗、改善株间通风、清理病残体，并记录斑点是否扩展到新叶或果实。化学防治选择有限且可能存在抗性，应咨询当地农技人员并遵守当地登记标签。', '["番茄", "细菌性斑点病", "叶斑", "高湿", "飞溅传播", "工具消毒"]', 'University of Minnesota Extension', 'https://extension.umn.edu/disease-management/bacterial-spot-tomato-and-pepper', 'Reviewed 2021' WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = 'KB-TOMATO-BACTERIAL-SPOT-001');

INSERT INTO knowledge_base (disease_id, source_code, title, content, tags, source_org, source_url, source_updated) SELECT (SELECT id FROM diseases WHERE model_label = 'Potato___Early_blight'), 'KB-POTATO-EARLY-BLIGHT-001', '马铃薯早疫病：症状、风险与管理', '马铃薯早疫病多先出现在较老或衰老叶片，病斑常为圆形至不规则深褐色斑，内部可形成靶纹状同心轮纹；严重时叶片黄化并脱落，块茎可能出现褐色木栓化干腐。病原可在病残体、土壤、块茎及其他茄科植物上存留，温暖且叶面有露水、降雨或喷灌水时容易侵染和扩展。在等待复核期间，应标记病株、清除严重病叶并妥善处理，避免湿叶操作，检查植株是否存在缺水、缺肥或其他虫害胁迫，采用根部供水并保持均衡水肥。预防重点包括健康种薯、清除病残体和自生苗、与非茄科作物轮作、保持植株长势和定期巡查老叶。是否需要化学防治应结合发病时期和经济风险，由当地农技人员依据登记标签决定。', '["马铃薯", "早疫病", "同心轮纹", "老叶", "植株胁迫", "轮作"]', 'UC Statewide IPM Program', 'https://ipm.ucanr.edu/agriculture/potato/early-blight/', 'Treatment table updated 2019' WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = 'KB-POTATO-EARLY-BLIGHT-001');

INSERT INTO knowledge_base (disease_id, source_code, title, content, tags, source_org, source_url, source_updated) SELECT (SELECT id FROM diseases WHERE model_label = 'Potato___Late_blight'), 'KB-POTATO-LATE-BLIGHT-001', '马铃薯晚疫病：快速扩展风险与管理', '马铃薯晚疫病可侵染全部地上部位。叶片初期可见淡绿至深绿色、不规则水渍状斑，随后迅速扩大并变为褐色至紫黑色；湿度充足时，病斑边缘尤其叶背可能出现白色孢子层，茎和叶柄也可出现褐黑色病斑。病原可能来自带病种薯、废薯堆、自生马铃薯、茄科杂草或邻近受害的马铃薯和番茄；高湿和凉爽潮湿条件有利于快速传播。若病斑在短时间内明显扩大，应立即减少人员和工具在湿植株间移动，隔离可疑区域，停止会延长叶面湿润的浇水方式，检查叶背、茎和邻近植株并每天记录扩展情况。使用健康种薯、清理废薯堆和自生苗、改善田间排水与叶面干燥速度是重要预防措施。晚疫病可能迅速造成严重损失，疑似成片发生时应尽快联系当地农技或植保机构确认并制定当地合规方案。', '["马铃薯", "晚疫病", "水渍状病斑", "白色霉层", "低温高湿", "快速扩展"]', 'UC Statewide IPM Program', 'https://ipm.ucanr.edu/agriculture/potato/late-blight/', 'UC IPM Potato Pest Management Guidelines' WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = 'KB-POTATO-LATE-BLIGHT-001');

INSERT INTO knowledge_base (disease_id, source_code, title, content, tags, source_org, source_url, source_updated) SELECT (SELECT id FROM diseases WHERE model_label = 'Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot'), 'KB-CORN-GRAY-LEAF-SPOT-001', '玉米灰斑病：症状、环境风险与管理', '玉米灰斑病常先在较低叶片出现，病斑狭长、矩形、浅褐色，后期可变灰，边界通常受到叶脉限制；多个病斑连接时可能导致整片叶组织死亡。病原可在玉米病残体中存活，因此连作玉米和残体较多的地块风险更高；孢子可随风和飞溅水传播，温暖且长时间高湿的天气有利于发病。在等待复核期间，应沿田间路线检查下部叶片和穗位叶附近是否存在典型矩形病斑，记录受病植株比例、病斑向上扩展速度、近期高湿或降雨情况，并避免把病残体和工具带到其他地块。预防措施包括选用抗性品种、合理轮作和病残体管理。是否需要进一步防治必须综合品种感病性、生育期、病害位置、天气和经济风险，由当地农技人员判断。', '["玉米", "灰斑病", "矩形病斑", "叶脉限制", "高温高湿", "病残体"]', 'Crop Protection Network', 'https://cropprotectionnetwork.org/encyclopedia/gray-leaf-spot-of-corn', 'Published 2019' WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = 'KB-CORN-GRAY-LEAF-SPOT-001');

INSERT INTO knowledge_base (disease_id, source_code, title, content, tags, source_org, source_url, source_updated) SELECT (SELECT id FROM diseases WHERE model_label = 'Tomato___Early_blight'), 'KB-TOMATO-EARLY-BLIGHT-001', '番茄早疫病：靶纹病斑与田间管理', '番茄早疫病通常先出现在植株下部较老叶片，常见圆形褐色病斑和靶纹状同心轮纹，病斑周围组织可能黄化；病害也可能侵染茎和果实。病原可随病残体、土壤、种子或带病苗传播，温暖、潮湿以及叶面长时间湿润时更容易发展。在等待复核期间，可标记病株，分次去除严重病叶且单次不超过植株叶量的三分之一，避免湿叶操作，采用根部浇水或滴灌，并用覆盖物减少土壤飞溅。预防重点包括扩大株间距、支架整枝改善通风、清理病残体、工具清洁和与非茄科作物轮作。若病斑快速向上扩展或果实受害，应联系当地农技人员确认。', '["番茄", "早疫病", "老叶", "同心轮纹", "温暖潮湿", "病残体"]', 'University of Minnesota Extension', 'https://extension.umn.edu/disease-management/early-blight-tomato-and-potato', 'Accessed 2026-08-13' WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = 'KB-TOMATO-EARLY-BLIGHT-001');

INSERT INTO knowledge_base (disease_id, source_code, title, content, tags, source_org, source_url, source_updated) SELECT (SELECT id FROM diseases WHERE model_label = 'Tomato___Late_blight'), 'KB-TOMATO-LATE-BLIGHT-001', '番茄晚疫病：快速扩展风险与应对', '番茄晚疫病可造成叶片大块暗褐色病斑，边缘常呈灰绿色且不受叶脉限制，茎上可出现坚实的暗色病斑；高湿时叶背病斑边缘可能出现白色生长物。凉爽、潮湿天气有利于病害迅速扩展。在等待专业确认期间，应立即隔离可疑植株，停止喷灌并避免人员和工具在湿植株间移动，每天检查叶背、茎和邻株，记录病斑是否在短时间内扩大。保持叶面干燥、使用滴灌、改善通风和及时清理已确认的病株有助于降低传播。晚疫病可能造成严重损失，疑似症状成片出现或扩展很快时应尽快联系当地农技或植保机构。', '["番茄", "晚疫病", "暗褐色病斑", "白色霉层", "凉爽潮湿", "快速扩展"]', 'University of Minnesota Extension', 'https://extension.umn.edu/disease-management/late-blight', 'Accessed 2026-08-13' WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = 'KB-TOMATO-LATE-BLIGHT-001');

INSERT INTO knowledge_base (disease_id, source_code, title, content, tags, source_org, source_url, source_updated) SELECT (SELECT id FROM diseases WHERE model_label = 'Tomato___Leaf_Mold'), 'KB-TOMATO-LEAF-MOLD-001', '番茄叶霉病：高湿环境下的识别与管理', '番茄叶霉病在温室和高架棚等高湿环境中较常见，通常先侵染较老叶片。叶片正面可出现淡黄色斑，叶背对应位置可见橄榄绿至褐色的绒状霉层；相对湿度高于约85%时风险明显增加。孢子可随气流、喷灌水、工具和人员传播。在等待复核期间，应降低棚内湿度，增加通风和株间气流，改用根部浇水或滴灌，避免夜间叶片长时间湿润，并清除严重病叶后妥善处理。持续记录叶背霉层是否增多、是否由下部叶片向上扩展。预防重点是温湿度管理、工具清洁、病残体清理和选用抗性品种。', '["番茄", "叶霉病", "叶背霉层", "温室", "高湿", "通风"]', 'University of Minnesota Extension', 'https://extension.umn.edu/disease-management/tomato-leaf-mold', 'Accessed 2026-08-13' WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = 'KB-TOMATO-LEAF-MOLD-001');

INSERT INTO knowledge_base (disease_id, source_code, title, content, tags, source_org, source_url, source_updated) SELECT (SELECT id FROM diseases WHERE model_label = 'Tomato___Septoria_leaf_spot'), 'KB-TOMATO-SEPTORIA-LEAF-SPOT-001', '番茄斑枯病：小型叶斑与管理', '番茄斑枯病常先在下部叶片出现大量较小的圆形褐色或黑色斑点，斑点中心可逐渐变为灰白或浅褐色，并可能出现细小黑点；症状与其他叶斑病相似，需要结合病斑形态和专业检查区分。高湿、降雨、喷灌飞溅和叶面长时间湿润有利于传播。在等待复核期间，可去除症状明显的下部病叶但单次不超过总叶量的三分之一，使用支架和合理间距改善通风，覆盖土表并从植株基部浇水。清洁工具、清除病残体和轮作有助于预防。应记录新叶是否持续出现小斑点以及病害向上发展的速度。', '["番茄", "斑枯病", "下部叶片", "小圆斑", "高湿", "根部浇水"]', 'University of Minnesota Extension', 'https://extension.umn.edu/plant-diseases/tomato-leaf-spot-diseases', 'Accessed 2026-08-13' WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = 'KB-TOMATO-SEPTORIA-LEAF-SPOT-001');

INSERT INTO knowledge_base (disease_id, source_code, title, content, tags, source_org, source_url, source_updated) SELECT (SELECT id FROM diseases WHERE model_label = 'Tomato___Spider_mites Two-spotted_spider_mite'), 'KB-TOMATO-TWO-SPOTTED-SPIDER-MITE-001', '番茄二斑叶螨：刺吸斑点、结网与低风险处理', '二斑叶螨体形很小，常在叶背取食，使叶片出现细密白色或黄色失绿斑点、斑驳和逐渐褐化；虫量较大时叶片和嫩梢间可见细丝网。高温干燥和植株缺水时更容易暴发。可用白纸轻拍叶片观察是否有微小活动虫体，并用放大镜检查叶背和结网。在等待复核期间，保持植株合理供水，用适度水流冲洗叶背并隔离重度受害植株，每3至5天复查一次，同时保护捕食螨等天敌，避免不必要的广谱杀虫处理。若范围持续扩大，应请当地农技人员确认虫情并选择当地登记措施。', '["番茄", "二斑叶螨", "叶背", "失绿斑点", "结网", "高温干燥"]', 'University of Minnesota Extension', 'https://extension.umn.edu/yard-and-garden-insects/spider-mites', 'Accessed 2026-08-13' WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = 'KB-TOMATO-TWO-SPOTTED-SPIDER-MITE-001');

INSERT INTO knowledge_base (disease_id, source_code, title, content, tags, source_org, source_url, source_updated) SELECT (SELECT id FROM diseases WHERE model_label = 'Tomato___Target_Spot'), 'KB-TOMATO-TARGET-SPOT-001', '番茄靶斑病：相似叶斑的复核与管理', '番茄靶斑病可在叶片和果实形成病斑，并可能造成明显落叶；其叶斑外观可能与早疫病、斑枯病及细菌性斑点病相似，仅凭单张图片不宜确诊。在等待复核期间，应拍摄叶片正反面、植株整体和果实，标记最早发病位置并记录扩展速度；去除严重病叶和落叶，减少喷灌造成的飞溅，改善通风并避免湿叶操作。预防重点包括使用健康种苗、清除茄科杂草和自生植株、处理病残体，并与非茄科作物轮作。病斑快速增多、严重落叶或果实受害时，应交由当地农技人员鉴别。', '["番茄", "靶斑病", "叶斑", "果斑", "落叶", "轮作"]', 'University of Florida IFAS Extension', 'https://edis.ifas.ufl.edu/publication/PP351', 'Accessed 2026-08-13' WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = 'KB-TOMATO-TARGET-SPOT-001');

INSERT INTO knowledge_base (disease_id, source_code, title, content, tags, source_org, source_url, source_updated) SELECT (SELECT id FROM diseases WHERE model_label = 'Tomato___Tomato_Yellow_Leaf_Curl_Virus'), 'KB-TOMATO-YELLOW-LEAF-CURL-VIRUS-001', '番茄黄化曲叶病毒病：症状、白粉虱传播与管理', '番茄黄化曲叶病毒病常表现为新叶变小、皱缩并向上卷曲，叶缘或叶脉间黄化，节间缩短、植株矮化，严重时落花和减产。病毒主要由烟粉虱传播，也可随带毒移栽苗进入田间。在等待复核期间，应检查叶背是否有白粉虱，将疑似植株与健康苗隔离，清除周围茄科杂草和自生番茄，并避免把疑似苗移到其他地块。发病率较低时，可在专业指导下及时移除病株；预防重点是健康种苗、抗性品种、苗期防虫和持续监测白粉虱。病毒病不能靠常规杀菌措施治愈，应由当地农技人员确认后制定综合管理方案。', '["番茄", "黄化曲叶病毒病", "叶片上卷", "黄化", "植株矮化", "白粉虱"]', 'UC Statewide IPM Program', 'https://ipm.ucanr.edu/agriculture/tomato/tomato-yellow-leaf-curl/', 'Accessed 2026-08-13' WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = 'KB-TOMATO-YELLOW-LEAF-CURL-VIRUS-001');

INSERT INTO knowledge_base (disease_id, source_code, title, content, tags, source_org, source_url, source_updated) SELECT (SELECT id FROM diseases WHERE model_label = 'Tomato___Tomato_mosaic_virus'), 'KB-TOMATO-MOSAIC-VIRUS-001', '番茄花叶病毒病：机械传播风险与卫生管理', '番茄花叶病毒病可表现为深浅绿色相间的花叶、叶片变形，凉爽条件下有时出现蕨叶状或细带状叶片，果实也可能出现异常斑纹。病毒可通过手部接触、工具、带毒种子、病残体以及烟草制品机械传播，并可长期保持活性。在等待复核期间，应隔离疑似植株，先操作健康植株再接触病株，操作前后清洁双手和工具，避免吸烟或接触烟草制品后直接触碰番茄，并妥善清理病残体。预防重点包括经处理的健康种子、抗性品种和严格卫生措施。疑似植株应由专业人员确认；病毒病不能依靠常规杀菌措施治愈。', '["番茄", "花叶病毒病", "花叶", "叶片畸形", "机械传播", "工具消毒"]', 'UC Statewide IPM Program', 'https://ipm.ucanr.edu/agriculture/tomato/tobacco-mosaic/', 'Accessed 2026-08-13' WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = 'KB-TOMATO-MOSAIC-VIRUS-001');

INSERT INTO knowledge_base (disease_id, source_code, title, content, tags, source_org, source_url, source_updated) SELECT (SELECT id FROM diseases WHERE model_label = 'Tomato___healthy'), 'KB-TOMATO-HEALTHY-001', '番茄健康状态：日常养护与持续观察', '模型判断为健康只表示当前图片未显示出明显的已学习病害特征，不能排除尚未显现、未被模型覆盖或图片未拍到的问题。日常应保持土壤水分相对稳定，从植株基部浇水并尽量避免叶片长时间湿润，使用合理株距和支架改善通风，及时清理落叶和病残体。建议每周检查叶片正反面、茎和果实，记录是否新出现斑点、黄化、卷叶、虫体或结网；若症状持续、快速扩展或植株生长明显异常，应重新拍摄并咨询当地农技人员。轮作、清洁工具和使用健康种苗有助于长期预防。', '["番茄", "健康", "养护", "根部浇水", "通风", "定期巡查"]', 'University of Minnesota Extension', 'https://extension.umn.edu/vegetables/growing-tomatoes', 'Accessed 2026-08-13' WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = 'KB-TOMATO-HEALTHY-001');

COMMIT;
SET SESSION sql_mode = @HEZHEN_OLD_SQL_MODE;
