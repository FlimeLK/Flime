-- HeroConfig: усі герої гри (оригінальні персонажі).
-- ВАЖЛИВО: ніколи не видаляй і не перейменовуй id героя після релізу —
-- id зберігається в DataStore, і гравці втратять цих героїв.
--
-- damage       — базова шкода (знадобиться в боях, етап 2)
-- attackSpeed  — атак за секунду
-- income       — монет за секунду на базі (рівень 1)
-- ability      — особлива здібність (працюватиме в боях)
-- awakened     — пробуджена форма (відкриється на наступних етапах)
-- look         — кольори простої моделі з Part

local HeroConfig = {}

HeroConfig.ElementColors = {
	Fire = Color3.fromRGB(255, 95, 40),
	Water = Color3.fromRGB(40, 150, 255),
	Lightning = Color3.fromRGB(255, 225, 50),
	Wind = Color3.fromRGB(90, 230, 140),
	Shadow = Color3.fromRGB(140, 60, 220),
	Light = Color3.fromRGB(255, 250, 200),
}

HeroConfig.ElementIcons = {
	Fire = "🔥",
	Water = "💧",
	Lightning = "⚡",
	Wind = "🍃",
	Shadow = "🌑",
	Light = "✨",
}

local SKIN = Color3.fromRGB(255, 220, 190)

HeroConfig.List = {
	-- ===== Common =====
	{
		id = "riku_windstep",
		name = "Riku Windstep",
		rarity = "Common",
		archetype = "Ninja",
		element = "Wind",
		damage = 4,
		attackSpeed = 1.2,
		income = 1,
		ability = { name = "Leaf Step", description = "Кожна 5-та атака б'є двічі." },
		awakened = { name = "Riku, Storm Leaf", multiplier = 2.5 },
		look = { body = Color3.fromRGB(60, 120, 80), hair = Color3.fromRGB(40, 40, 40), skin = SKIN, height = 0.9 },
	},
	{
		id = "tomo_deckhand",
		name = "Tomo the Deckhand",
		rarity = "Common",
		archetype = "Pirate",
		element = "Water",
		damage = 5,
		attackSpeed = 0.9,
		income = 1,
		ability = { name = "Barrel Toss", description = "Кидає бочку, що оглушує ворога на 0.5 с." },
		awakened = { name = "Tomo, Tide Breaker", multiplier = 2.5 },
		look = { body = Color3.fromRGB(230, 230, 230), hair = Color3.fromRGB(120, 70, 30), skin = SKIN, height = 0.95 },
	},
	{
		id = "hana_emberling",
		name = "Hana Emberling",
		rarity = "Common",
		archetype = "Mage",
		element = "Fire",
		damage = 6,
		attackSpeed = 0.8,
		income = 1.2,
		ability = { name = "Tiny Flame", description = "Підпалює ворога: +10% шкоди протягом 3 с." },
		awakened = { name = "Hana, Bright Cinder", multiplier = 2.5 },
		look = { body = Color3.fromRGB(200, 70, 70), hair = Color3.fromRGB(255, 150, 60), skin = SKIN, height = 0.9 },
	},
	{
		id = "zen_cadet",
		name = "Zen Star Cadet",
		rarity = "Common",
		archetype = "Space Warrior",
		element = "Lightning",
		damage = 5,
		attackSpeed = 1,
		income = 1.1,
		ability = { name = "Blaster Burst", description = "Три швидкі постріли поспіль." },
		awakened = { name = "Zen, Orbit Ranger", multiplier = 2.5 },
		look = { body = Color3.fromRGB(80, 90, 120), hair = Color3.fromRGB(240, 240, 240), skin = SKIN, height = 1 },
	},

	-- ===== Rare =====
	{
		id = "shiro_quickblade",
		name = "Shiro Quickblade",
		rarity = "Rare",
		archetype = "Swordsman",
		element = "Lightning",
		damage = 14,
		attackSpeed = 1.1,
		income = 3,
		ability = { name = "Flash Draw", description = "Перший удар по ворогу завдає подвійної шкоди." },
		awakened = { name = "Shiro, Thunder Sheath", multiplier = 2.6 },
		look = { body = Color3.fromRGB(240, 240, 250), hair = Color3.fromRGB(220, 220, 230), skin = SKIN, height = 1.05 },
	},
	{
		id = "kaito_saltfang",
		name = "Kaito Saltfang",
		rarity = "Rare",
		archetype = "Pirate",
		element = "Water",
		damage = 16,
		attackSpeed = 0.9,
		income = 3.2,
		ability = { name = "Anchor Drop", description = "Б'є якорем по площі навколо цілі." },
		awakened = { name = "Kaito, Deepwater Fang", multiplier = 2.6 },
		look = { body = Color3.fromRGB(40, 60, 110), hair = Color3.fromRGB(20, 20, 30), skin = SKIN, height = 1.1 },
	},
	{
		id = "mira_cinderveil",
		name = "Mira Cinderveil",
		rarity = "Rare",
		archetype = "Mage",
		element = "Fire",
		damage = 18,
		attackSpeed = 0.8,
		income = 3.5,
		ability = { name = "Ash Veil", description = "Зменшує шкоду від босів на 15% для команди." },
		awakened = { name = "Mira, Veil of Embers", multiplier = 2.6 },
		look = { body = Color3.fromRGB(120, 30, 40), hair = Color3.fromRGB(250, 220, 120), skin = SKIN, height = 1 },
	},
	{
		id = "yoru_lantern",
		name = "Yoru Lanternbearer",
		rarity = "Rare",
		archetype = "Demon Hunter",
		element = "Shadow",
		damage = 15,
		attackSpeed = 1,
		income = 3,
		ability = { name = "Spirit Lantern", description = "+25% шкоди по демонам і нічним ворогам." },
		awakened = { name = "Yoru, Night Watcher", multiplier = 2.6 },
		look = { body = Color3.fromRGB(40, 35, 60), hair = Color3.fromRGB(90, 50, 140), skin = SKIN, height = 1.05 },
	},

	-- ===== Epic =====
	{
		id = "akane_crimsonfan",
		name = "Akane Crimson Fan",
		rarity = "Epic",
		archetype = "Ninja",
		element = "Fire",
		damage = 40,
		attackSpeed = 1.2,
		income = 8,
		ability = { name = "Crimson Fan Dance", description = "Вогняний вихор б'є всіх ворогів поруч." },
		awakened = { name = "Akane, Scarlet Tempest", multiplier = 2.8 },
		look = { body = Color3.fromRGB(180, 20, 40), hair = Color3.fromRGB(30, 10, 10), skin = SKIN, height = 1 },
	},
	{
		id = "raizo_thunderstep",
		name = "Raizo Thunderstep",
		rarity = "Epic",
		archetype = "Ninja",
		element = "Lightning",
		damage = 42,
		attackSpeed = 1.3,
		income = 8.5,
		ability = { name = "Thunder Step", description = "Телепортується до цілі й оглушує її." },
		awakened = { name = "Raizo, Storm Phantom", multiplier = 2.8 },
		look = { body = Color3.fromRGB(30, 30, 50), hair = Color3.fromRGB(255, 220, 60), skin = SKIN, height = 1.05 },
	},
	{
		id = "nox_hollowhunter",
		name = "Nox Hollowhunter",
		rarity = "Epic",
		archetype = "Demon Hunter",
		element = "Shadow",
		damage = 45,
		attackSpeed = 1,
		income = 9,
		ability = { name = "Hollow Mark", description = "Позначена ціль отримує +30% шкоди." },
		awakened = { name = "Nox, Abyss Warden", multiplier = 2.8 },
		look = { body = Color3.fromRGB(20, 20, 25), hair = Color3.fromRGB(230, 230, 240), skin = SKIN, height = 1.15 },
	},
	{
		id = "coral_vex",
		name = "Captain Coral Vex",
		rarity = "Epic",
		archetype = "Pirate",
		element = "Water",
		damage = 38,
		attackSpeed = 1,
		income = 8,
		ability = { name = "Broadside", description = "Залп гармат: 5 снарядів по випадкових ворогах." },
		awakened = { name = "Coral Vex, Reef Admiral", multiplier = 2.8 },
		look = { body = Color3.fromRGB(240, 120, 140), hair = Color3.fromRGB(255, 160, 170), skin = SKIN, height = 1.05 },
	},

	-- ===== Legendary =====
	{
		id = "seren_starblade",
		name = "Seren Starblade",
		rarity = "Legendary",
		archetype = "Space Warrior",
		element = "Light",
		damage = 110,
		attackSpeed = 1.1,
		income = 25,
		ability = { name = "Starfall Edge", description = "Кожна 4-та атака викликає падіння зірки." },
		awakened = { name = "Seren, Galaxy Blade", multiplier = 3 },
		look = { body = Color3.fromRGB(240, 240, 255), hair = Color3.fromRGB(150, 200, 255), skin = SKIN, height = 1.15 },
	},
	{
		id = "kuro_moonreaper",
		name = "Kuro Moonreaper",
		rarity = "Legendary",
		archetype = "Swordsman",
		element = "Shadow",
		damage = 120,
		attackSpeed = 1,
		income = 26,
		ability = { name = "Lunar Severance", description = "Удар-півмісяць, що проходить крізь усіх ворогів." },
		awakened = { name = "Kuro, Eclipse Reaper", multiplier = 3 },
		look = { body = Color3.fromRGB(25, 20, 40), hair = Color3.fromRGB(60, 40, 110), skin = SKIN, height = 1.2 },
	},
	{
		id = "homura_ashcrown",
		name = "Homura Ashcrown",
		rarity = "Legendary",
		archetype = "Mage",
		element = "Fire",
		damage = 125,
		attackSpeed = 0.9,
		income = 27,
		ability = { name = "Crown of Ash", description = "Палає вся арена: шкода всім ворогам щосекунди." },
		awakened = { name = "Homura, Inferno Monarch", multiplier = 3 },
		look = { body = Color3.fromRGB(60, 20, 20), hair = Color3.fromRGB(255, 80, 30), skin = SKIN, height = 1.1 },
	},
	{
		id = "ryo_skybolt",
		name = "Ryo Skybolt",
		rarity = "Legendary",
		archetype = "Swordsman",
		element = "Lightning",
		damage = 115,
		attackSpeed = 1.2,
		income = 25,
		ability = { name = "Sky Splitter", description = "Блискавка перескакує між 4 ворогами." },
		awakened = { name = "Ryo, Heaven's Bolt", multiplier = 3 },
		look = { body = Color3.fromRGB(30, 50, 90), hair = Color3.fromRGB(255, 240, 120), skin = SKIN, height = 1.15 },
	},

	-- ===== Mythic =====
	{
		id = "astra_novaempress",
		name = "Astra, Nova Empress",
		rarity = "Mythic",
		archetype = "Space Warrior",
		element = "Light",
		damage = 320,
		attackSpeed = 1,
		income = 80,
		ability = { name = "Supernova", description = "Вибух зірки: величезна шкода всім і щит команді." },
		awakened = { name = "Astra, Cosmic Sovereign", multiplier = 3.3 },
		look = { body = Color3.fromRGB(255, 240, 200), hair = Color3.fromRGB(255, 200, 255), skin = SKIN, height = 1.2 },
	},
	{
		id = "gekko_voidshinobi",
		name = "Gekko the Void Shinobi",
		rarity = "Mythic",
		archetype = "Ninja",
		element = "Shadow",
		damage = 340,
		attackSpeed = 1.3,
		income = 85,
		ability = { name = "Void Clone", description = "Створює 2 тіньові клони, що атакують разом із ним." },
		awakened = { name = "Gekko, Endless Night", multiplier = 3.3 },
		look = { body = Color3.fromRGB(15, 10, 25), hair = Color3.fromRGB(180, 80, 255), skin = SKIN, height = 1.1 },
	},
	{
		id = "volta_stormcaptain",
		name = "Storm Captain Volta",
		rarity = "Mythic",
		archetype = "Pirate",
		element = "Lightning",
		damage = 330,
		attackSpeed = 1.1,
		income = 82,
		ability = { name = "Tempest Cannon", description = "Гармата-блискавка, що пробиває броню босів." },
		awakened = { name = "Volta, Tempest Queen", multiplier = 3.3 },
		look = { body = Color3.fromRGB(40, 40, 70), hair = Color3.fromRGB(120, 230, 255), skin = SKIN, height = 1.15 },
	},
	{
		id = "ifra_phoenixsaint",
		name = "Ifra, Phoenix Saint",
		rarity = "Mythic",
		archetype = "Mage",
		element = "Fire",
		damage = 335,
		attackSpeed = 1,
		income = 83,
		ability = { name = "Rebirth Flame", description = "Раз за бій воскрешає союзника з повним здоров'ям." },
		awakened = { name = "Ifra, Eternal Phoenix", multiplier = 3.3 },
		look = { body = Color3.fromRGB(255, 150, 40), hair = Color3.fromRGB(255, 60, 20), skin = SKIN, height = 1.15 },
	},

	-- ===== Secret =====
	{
		id = "solenne_eclipse",
		name = "Solenne, Eclipse Sovereign",
		rarity = "Secret",
		archetype = "Mage",
		element = "Light",
		damage = 1000,
		attackSpeed = 1,
		income = 300,
		ability = { name = "Total Eclipse", description = "Зупиняє час для ворогів на 3 с." },
		awakened = { name = "Solenne, Dawn and Dusk", multiplier = 4 },
		look = { body = Color3.fromRGB(250, 245, 255), hair = Color3.fromRGB(255, 215, 100), skin = SKIN, height = 1.25 },
	},
	{
		id = "mugen_dicegod",
		name = "Mugen, the Dice God",
		rarity = "Secret",
		archetype = "Space Warrior",
		element = "Shadow",
		damage = 1100,
		attackSpeed = 1.2,
		income = 320,
		ability = { name = "Loaded Fate", description = "Кожна атака кидає кубик: шкода ×1…×6." },
		awakened = { name = "Mugen, Infinite Roll", multiplier = 4 },
		look = { body = Color3.fromRGB(20, 15, 30), hair = Color3.fromRGB(40, 255, 210), skin = SKIN, height = 1.3 },
	},
}

-- Швидкий доступ: HeroConfig.Heroes[id] і HeroConfig.ByRarity[rarity]
HeroConfig.Heroes = {}
HeroConfig.ByRarity = {}

for _, hero in HeroConfig.List do
	assert(HeroConfig.Heroes[hero.id] == nil, "Duplicate hero id: " .. hero.id)
	HeroConfig.Heroes[hero.id] = hero
	HeroConfig.ByRarity[hero.rarity] = HeroConfig.ByRarity[hero.rarity] or {}
	table.insert(HeroConfig.ByRarity[hero.rarity], hero)
end

return HeroConfig
