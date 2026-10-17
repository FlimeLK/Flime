-- DiceConfig: усі кубики гри.
-- price         — ціна одного кидка в Coins
-- luck          — множник удачі (діє на рідкості з luckAffected = true)
-- requiredRolls — скільки всього кидків треба зробити, щоб відкрити кубик
-- requiredBoss  — (необов'язково) id боса, якого треба перемогти хоча б раз
-- element       — стихія, герої якої випадають частіше
-- elementBonus  — у скільки разів частіше випадають герої цієї стихії
-- weights       — базові ваги рідкостей (не обов'язково в сумі 100)

local DiceConfig = {}

-- Кубик, яким робиться перший безкоштовний навчальний кидок.
DiceConfig.TutorialDice = "Basic"

DiceConfig.Order = { "Basic", "Fire", "Lightning", "Shadow", "Tidal", "Celestial" }

DiceConfig.Dice = {
	Basic = {
		displayName = "Basic Dice",
		description = "Простий кубик для старту пригоди.",
		icon = "🎲",
		color = Color3.fromRGB(235, 235, 245),
		price = 25,
		luck = 1,
		requiredRolls = 0,
		element = nil,
		elementBonus = 1,
		weights = { Common = 700, Rare = 230, Epic = 60, Legendary = 9, Mythic = 1, Secret = 0 },
	},
	Fire = {
		displayName = "Fire Dice",
		description = "Вогняні герої випадають утричі частіше.",
		icon = "🔥",
		color = Color3.fromRGB(255, 110, 50),
		price = 150,
		luck = 1.25,
		requiredRolls = 25,
		element = "Fire",
		elementBonus = 3,
		weights = { Common = 600, Rare = 280, Epic = 95, Legendary = 20, Mythic = 4.5, Secret = 0.5 },
	},
	Lightning = {
		displayName = "Lightning Dice",
		description = "Блискавичні герої випадають утричі частіше.",
		icon = "⚡",
		color = Color3.fromRGB(255, 230, 60),
		price = 600,
		luck = 1.5,
		requiredRolls = 75,
		element = "Lightning",
		elementBonus = 3,
		weights = { Common = 500, Rare = 320, Epic = 130, Legendary = 38, Mythic = 10, Secret = 2 },
	},
	Shadow = {
		displayName = "Shadow Dice",
		description = "Тіньові герої випадають утричі частіше.",
		icon = "🌑",
		color = Color3.fromRGB(120, 60, 200),
		price = 2500,
		luck = 1.8,
		requiredRolls = 200,
		element = "Shadow",
		elementBonus = 3,
		weights = { Common = 380, Rare = 340, Epic = 180, Legendary = 70, Mythic = 25, Secret = 5 },
	},
	Tidal = {
		displayName = "Tidal Dice",
		description = "Нагорода за Captain Blackwake. Водні герої втричі частіше.",
		icon = "🌊",
		color = Color3.fromRGB(40, 170, 255),
		price = 5000,
		luck = 2,
		requiredRolls = 0,
		requiredBoss = "captain_blackwake",
		element = "Water",
		elementBonus = 3,
		weights = { Common = 300, Rare = 340, Epic = 210, Legendary = 100, Mythic = 40, Secret = 10 },
	},
	Celestial = {
		displayName = "Celestial Dice",
		description = "Небесний кубик: найкраща удача, світлі герої частіше.",
		icon = "✨",
		color = Color3.fromRGB(150, 230, 255),
		price = 10000,
		luck = 2.2,
		requiredRolls = 500,
		element = "Light",
		elementBonus = 3,
		weights = { Common = 250, Rare = 330, Epic = 230, Legendary = 120, Mythic = 55, Secret = 15 },
	},
}

return DiceConfig
