-- EconomyConfig: ціни, бонуси та ліміти. Усі числа балансу — тут.

local EconomyConfig = {
	StartingCoins = 60,
	StartingCrystals = 0,
	MaxInventory = 150, -- максимум героїв в інвентарі

	-- База
	StartSlots = 3,
	MaxSlots = 12,
	SlotUpgrade = {
		basePrice = 150, -- ціна 4-го слота
		growth = 1.9, -- кожен наступний слот дорожчий у 1.9 раза
	},
	IncomeUpgrade = {
		basePrice = 100,
		growth = 1.55,
		bonusPerLevel = 0.1, -- +10% доходу бази за рівень
		maxLevel = 30,
	},

	-- Герої
	LevelIncomeBonus = 0.2, -- +20% доходу героя за кожен рівень понад 1
	LevelDamageBonus = 0.15, -- +15% шкоди за рівень (знадобиться в боях)
	SellLevelBonus = 0.5, -- кожен рівень додає 50% до ціни продажу

	-- Дохід
	IncomeTickSeconds = 1,
	OfflineMaxSeconds = 2 * 60 * 60, -- офлайн-дохід максимум за 2 години
	OfflineRate = 0.5, -- офлайн герої заробляють 50% від звичайного

	-- Rebirth: віддаєш монети, слоти й покращення доходу — отримуєш назавжди
	-- +50% доходу і +5% удачі за кожен Rebirth та кристали.
	Rebirth = {
		baseCost = 250000, -- ціна першого Rebirth у Coins
		growth = 2.5, -- кожен наступний дорожчий у 2.5 раза
		incomeBonus = 0.5,
		luckBonus = 0.05,
		crystalReward = 10, -- × номер Rebirth (10, 20, 30…)
	},

	-- Колекція: кожен відкритий герой дає +2% до доходу бази
	CollectionIncomeBonus = 0.02,

	-- Кидки
	RollCooldown = 0.5, -- мінімальна пауза між кидками (сервер)

	-- Гарантія: якщо N кидків поспіль не випадало rarity або краще,
	-- N-й кидок гарантовано дасть щонайменше цю рідкість.
	Pity = {
		{ rarity = "Epic", rolls = 40 },
		{ rarity = "Legendary", rolls = 250 },
	},
}

return EconomyConfig
