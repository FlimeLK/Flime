-- ShopConfig: покупки за Crystals.
-- Boosts — тимчасові підсилення (діють за серверним часом, навіть офлайн спливає час).
-- Items  — товари магазину.

local ShopConfig = {}

ShopConfig.Boosts = {
	luck = { displayName = "🍀 Удача", multiplier = 2 },
	income = { displayName = "💰 Дохід", multiplier = 2 },
}

ShopConfig.Order = { "LuckPotion", "CoinPotion", "BigBag" }

ShopConfig.Items = {
	LuckPotion = {
		displayName = "🍀 Зілля удачі",
		description = "Удача ×2 для всіх кубиків на 10 хв",
		kind = "boost",
		boost = "luck",
		price = 5,
		duration = 10 * 60,
		maxDuration = 60 * 60, -- можна накопичити максимум годину
	},
	CoinPotion = {
		displayName = "💰 Зілля монет",
		description = "Дохід бази ×2 на 10 хв",
		kind = "boost",
		boost = "income",
		price = 5,
		duration = 10 * 60,
		maxDuration = 60 * 60,
	},
	BigBag = {
		displayName = "🎒 Більша сумка",
		description = "+25 місць в інвентарі назавжди",
		kind = "inventory",
		amount = 25,
		basePrice = 10, -- 10, 20, 30, 40 💎
		priceStep = 10,
		maxPurchases = 4,
	},
}

return ShopConfig
