-- RarityConfig: рідкості героїв.
-- rank          — порядок (чим більше, тим рідкісніше)
-- luckAffected  — чи множиться шанс на удачу кубика
-- sellPrice     — базова ціна продажу (множиться на рівень)
-- maxLevel      — максимальний рівень через злиття дублікатів
-- autoLock      — герой одразу блокується від випадкового продажу
-- aura / light  — візуальні ефекти героя на базі

local RarityConfig = {}

RarityConfig.Order = { "Common", "Rare", "Epic", "Legendary", "Mythic", "Secret" }

RarityConfig.Info = {
	Common = {
		rank = 1,
		color = Color3.fromRGB(200, 200, 210),
		luckAffected = false,
		sellPrice = 5,
		maxLevel = 10,
		autoLock = false,
		aura = false,
		light = false,
	},
	Rare = {
		rank = 2,
		color = Color3.fromRGB(70, 150, 255),
		luckAffected = true,
		sellPrice = 20,
		maxLevel = 15,
		autoLock = false,
		aura = false,
		light = false,
	},
	Epic = {
		rank = 3,
		color = Color3.fromRGB(175, 85, 255),
		luckAffected = true,
		sellPrice = 75,
		maxLevel = 20,
		autoLock = false,
		aura = true,
		light = false,
	},
	Legendary = {
		rank = 4,
		color = Color3.fromRGB(255, 190, 40),
		luckAffected = true,
		sellPrice = 300,
		maxLevel = 25,
		autoLock = true,
		aura = true,
		light = false,
	},
	Mythic = {
		rank = 5,
		color = Color3.fromRGB(255, 60, 100),
		luckAffected = true,
		sellPrice = 1500,
		maxLevel = 30,
		autoLock = true,
		aura = true,
		light = true,
	},
	Secret = {
		rank = 6,
		color = Color3.fromRGB(40, 255, 210),
		luckAffected = true,
		sellPrice = 10000,
		maxLevel = 40,
		autoLock = true,
		aura = true,
		light = true,
	},
}

function RarityConfig.GetRank(rarity)
	local info = RarityConfig.Info[rarity]
	return info and info.rank or 0
end

function RarityConfig.GetColor(rarity)
	local info = RarityConfig.Info[rarity]
	return info and info.color or Color3.new(1, 1, 1)
end

return RarityConfig
