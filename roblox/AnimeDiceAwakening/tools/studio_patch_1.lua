-- Згенеровано tools/make_studio_patch.py — НЕ редагуй вручну.
-- Частина 1 з 7. Запускай усі частини по черзі: від 1 до 7.
-- Studio → зупини гру (Stop) → View → Command Bar → встав увесь текст → ▶ Run.
-- Замінює код скриптів нижче на нову версію. Ctrl+Z скасовує зміни.
local ChangeHistoryService = game:GetService("ChangeHistoryService")
local ScriptEditorService = game:GetService("ScriptEditorService")
local recording = ChangeHistoryService:TryBeginRecording("AnimeDiceAwakening patch")

local function setSource(path, className, source)
	local parent = game:GetService(path[1])
	for i = 2, #path - 1 do
		local child = parent:FindFirstChild(path[i])
		if not child then
			child = Instance.new("Folder")
			child.Name = path[i]
			child.Parent = parent
		end
		parent = child
	end
	local target = parent:FindFirstChild(path[#path])
	if target and not target:IsA(className) then
		warn("❌ " .. target:GetFullName() .. " — не " .. className .. ", пропускаю")
		return
	end
	if not target then
		target = Instance.new(className)
		target.Name = path[#path]
		target.Parent = parent
	end
	-- Через ScriptEditorService, щоб оновились і відкриті вкладки редактора
	local ok = pcall(function()
		ScriptEditorService:UpdateSourceAsync(target, function()
			return source
		end)
	end)
	if not ok then
		target.Source = source
	end
	print("✅ оновлено " .. target:GetFullName())
end

setSource({ "ReplicatedStorage", "Shared", "Config", "HeroArtConfig" }, "ModuleScript", [=[
-- HeroArtConfig: як виглядають герої — 3D-моделі з Creator Store і портрети.
--
-- Models   — ID безкоштовних моделей з Creator Store (Toolbox). Їх завантажує в
--            ReplicatedStorage/HeroModels скрипт tools/load_hero_models.lua (Command Bar → ▶ Run),
--            а гра ставить їх на базу, у команду й показує під час кидка.
-- Portraits — свої картинки героїв (ID з Asset Manager). Якщо порожньо, портретом
--            стає знімок моделі з Models — нічого завантажувати не треба.
--
-- Моделі підібрані в аніме-стилі й без персонажів чужих франшиз (Roblox видаляє ігри
-- з чужими персонажами за авторські права). Будь-який ID можна замінити на свій.

local HeroArtConfig = {}

HeroArtConfig.Models = {
	riku_windstep = 10465459303, -- Riku Windstep (Common)
	tomo_deckhand = 100944702942220, -- Tomo the Deckhand (Common)
	hana_emberling = 5267955171, -- Hana Emberling (Common)
	zen_cadet = 12757277166, -- Zen Star Cadet (Common)
	shiro_quickblade = 8988047057, -- Shiro Quickblade (Rare)
	kaito_saltfang = 132434304646924, -- Kaito Saltfang (Rare)
	mira_cinderveil = 14976197705, -- Mira Cinderveil (Rare)
	yoru_lantern = 102936851931650, -- Yoru Lanternbearer (Rare)
	akane_crimsonfan = 1002392746, -- Akane Crimson Fan (Epic)
	raizo_thunderstep = 12572205024, -- Raizo Thunderstep (Epic)
	nox_hollowhunter = 117056856525249, -- Nox Hollowhunter (Epic)
	coral_vex = 799516341, -- Captain Coral Vex (Epic)
	seren_starblade = 12864717820, -- Seren Starblade (Legendary)
	kuro_moonreaper = 133610989566243, -- Kuro Moonreaper (Legendary)
	homura_ashcrown = 5123918805, -- Homura Ashcrown (Legendary)
	ryo_skybolt = 88689760627068, -- Ryo Skybolt (Legendary)
	marisol_tidecaller = 2513353543, -- Marisol Tidecaller (Legendary)
	rin_hellbane = 9389951512, -- Rin Hellbane (Legendary)
	astra_novaempress = 1346868188, -- Astra, Nova Empress (Mythic)
	gekko_voidshinobi = 11965234368, -- Gekko the Void Shinobi (Mythic)
	volta_stormcaptain = 3552939059, -- Storm Captain Volta (Mythic)
	ifra_phoenixsaint = 79118375438271, -- Ifra, Phoenix Saint (Mythic)
	kaizen_deepcrown = 10854041153, -- Admiral Kaizen Deepcrown (Mythic)
	kagura_duskblade = 89208241488034, -- Kagura Duskblade (Mythic)
	solenne_eclipse = 7084656859, -- Solenne, Eclipse Sovereign (Secret)
	mugen_dicegod = 107515140283474, -- Mugen, the Dice God (Secret)
	vael_abyssal = 4856690928, -- Vael, Abyssal Emperor (Secret)
}

-- Свої портрети (необов'язково): "1234567890" або "rbxassetid://1234567890"
HeroArtConfig.Portraits = {
	riku_windstep = "",
	tomo_deckhand = "",
	hana_emberling = "",
	zen_cadet = "",
	shiro_quickblade = "",
	kaito_saltfang = "",
	mira_cinderveil = "",
	yoru_lantern = "",
	akane_crimsonfan = "",
	raizo_thunderstep = "",
	nox_hollowhunter = "",
	coral_vex = "",
	seren_starblade = "",
	kuro_moonreaper = "",
	homura_ashcrown = "",
	ryo_skybolt = "",
	marisol_tidecaller = "",
	rin_hellbane = "",
	astra_novaempress = "",
	gekko_voidshinobi = "",
	volta_stormcaptain = "",
	ifra_phoenixsaint = "",
	kaizen_deepcrown = "",
	kagura_duskblade = "",
	solenne_eclipse = "",
	mugen_dicegod = "",
	vael_abyssal = "",
}

-- true — якщо свого портрета немає, показувати знімок моделі з Creator Store
HeroArtConfig.ModelThumbnailPortraits = true

-- Адреса портрета героя або nil (тоді гра показує 3D-модель).
-- ownOnly = true — лише своя картинка, без знімка моделі (під час кидка краще жива 3D-модель).
function HeroArtConfig.GetPortrait(heroId, ownOnly)
	local image = HeroArtConfig.Portraits[heroId]
	if type(image) == "number" then
		image = tostring(image)
	end
	if type(image) == "string" and image ~= "" then
		if string.match(image, "^%d+$") then
			return "rbxassetid://" .. image
		end
		return image
	end
	local modelId = HeroArtConfig.Models[heroId]
	if not ownOnly and HeroArtConfig.ModelThumbnailPortraits and type(modelId) == "number" then
		return ("rbxthumb://type=Asset&id=%d&w=420&h=420"):format(modelId)
	end
	return nil
end

return HeroArtConfig
]=])

setSource({ "ReplicatedStorage", "Shared", "Config", "AdminConfig" }, "ModuleScript", [=[
-- AdminConfig: хто має доступ до адмін-панелі.
-- Кожну дію адміна сервер перевіряє заново — клієнт лише показує кнопки.

local AdminConfig = {}

-- Імена адмінів. Сервер сам перетворює їх на UserId (так надійніше, ніж порівнювати імена).
AdminConfig.Usernames = { "FlimeYTLK" }

-- UserId адмінів (необов'язково): числа з посилання на профіль roblox.com/users/<UserId>/profile
AdminConfig.UserIds = {}

-- Власник гри (або власник групи, якщо гра групова) — завжди адмін
AdminConfig.OwnerIsAdmin = true

-- У Studio (Play / Start Server) адмінами є всі тестові гравці — зручно перевіряти панель
AdminConfig.StudioIsAdmin = true

-- Межі, щоб випадковий нуль зайвий не зламав економіку
AdminConfig.MaxCurrency = 1e15
AdminConfig.MaxHeroesPerAction = 10
AdminConfig.MaxBoostMinutes = 24 * 60
AdminConfig.MaxEventMinutes = 120
AdminConfig.EventMultipliers = { 2, 3, 5, 10 }
AdminConfig.WalkSpeeds = { 16, 32, 60, 100 }
AdminConfig.LogSize = 60

return AdminConfig
]=])

setSource({ "ReplicatedStorage", "Shared", "Config", "DiceConfig" }, "ModuleScript", [=[
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

DiceConfig.Order = { "Basic", "Fire", "Lightning", "Shadow", "Tidal", "Celestial", "Abyss" }

DiceConfig.Dice = {
	Abyss = {
		displayName = "Abyss Dice",
		description = "Нагорода за Demon Queen Noctyra. Тіньові герої втричі частіше.",
		icon = "🔮",
		color = Color3.fromRGB(150, 40, 200),
		price = 25000,
		luck = 2.8,
		requiredRolls = 0,
		requiredBoss = "demon_queen_noctyra",
		element = "Shadow",
		elementBonus = 3,
		weights = { Common = 200, Rare = 300, Epic = 250, Legendary = 150, Mythic = 75, Secret = 25 },
	},
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
]=])

setSource({ "ReplicatedStorage", "Shared", "Config", "EnemyConfig" }, "ModuleScript", [=[
-- EnemyConfig: вороги, боси та де вони з'являються у кожному світі.
-- health   — запас здоров'я
-- coins    — нагорода в Coins кожному, хто допоміг перемогти
-- crystals — нагорода в Crystals (лише боси)
-- respawn  — через скільки секунд ворог з'явиться знову
-- style    — зовнішній вигляд простої моделі з Part
--
-- Атаки боса (attacks) — список; бос щоразу вибирає випадкову. pattern:
--   "self"    — коло навколо боса
--   "targets" — коло під кожним гравцем поруч
--   "random"  — count кіл у випадкових місцях арени (spread — радіус розкиду)

local EnemyConfig = {}

EnemyConfig.Enemies = {
	bandit_genin = {
		name = "Bandit Genin",
		health = 80,
		coins = 12,
		crystals = 0,
		respawn = 8,
		scale = 1,
		style = "Genin",
		body = Color3.fromRGB(90, 85, 75),
		accent = Color3.fromRGB(200, 60, 60),
	},
	shadow_puppet = {
		name = "Shadow Puppet",
		health = 240,
		coins = 32,
		crystals = 0,
		respawn = 10,
		scale = 1.1,
		style = "Puppet",
		body = Color3.fromRGB(35, 25, 50),
		accent = Color3.fromRGB(170, 80, 255),
	},
	rogue_ronin = {
		name = "Rogue Ronin",
		health = 650,
		coins = 85,
		crystals = 0,
		respawn = 14,
		scale = 1.25,
		style = "Ronin",
		body = Color3.fromRGB(60, 70, 110),
		accent = Color3.fromRGB(230, 230, 240),
	},
	oni_kurogane = {
		name = "Oni Warlord Kurogane",
		health = 6000,
		coins = 1500,
		crystals = 25,
		respawn = 90,
		scale = 2.6,
		style = "Oni",
		body = Color3.fromRGB(180, 40, 40),
		accent = Color3.fromRGB(255, 200, 60),
		isBoss = true,
		attackInterval = 5, -- секунд між атаками
		attacks = {
			-- Удар по землі навколо боса: червоне коло, потім шкода всім усередині
			{ displayName = "Ground Slam", pattern = "self", telegraph = 1.6, radius = 20, damage = 35 },
			-- Дощ сюрикенів: кола під кожним гравцем поруч, треба відбігти
			{ displayName = "Shuriken Rain", pattern = "targets", telegraph = 1.3, radius = 9, damage = 25 },
		},
	},

	-- ===== Pirate Island =====
	deckhand_brawler = {
		name = "Deckhand Brawler",
		health = 900,
		coins = 70,
		crystals = 0,
		respawn = 8,
		scale = 1.15,
		style = "Brawler",
		body = Color3.fromRGB(150, 110, 80),
		accent = Color3.fromRGB(220, 40, 40),
	},
	cannon_crab = {
		name = "Cannon Crab",
		health = 2200,
		coins = 160,
		crystals = 0,
		respawn = 10,
		scale = 1.3,
		style = "Crab",
		body = Color3.fromRGB(230, 90, 60),
		accent = Color3.fromRGB(60, 60, 70),
	},
	cursed_corsair = {
		name = "Cursed Corsair",
		health = 5000,
		coins = 350,
		crystals = 0,
		respawn = 14,
		scale = 1.35,
		style = "Corsair",
		body = Color3.fromRGB(40, 70, 80),
		accent = Color3.fromRGB(80, 255, 200),
	},
	captain_blackwake = {
		name = "Captain Blackwake",
		health = 45000,
		coins = 12000,
		crystals = 60,
		respawn = 120,
		scale = 2.8,
		style = "Captain",
		body = Color3.fromRGB(30, 30, 45),
		accent = Color3.fromRGB(255, 200, 60),
		isBoss = true,
		attackInterval = 4.5,
		attacks = {
			{ displayName = "Cannon Barrage", pattern = "random", count = 7, spread = 26, telegraph = 1.5, radius = 8, damage = 40 },
			{ displayName = "Anchor Sweep", pattern = "self", telegraph = 1.8, radius = 24, damage = 50 },
			{ displayName = "Kraken Grab", pattern = "targets", telegraph = 1.4, radius = 10, damage = 45 },
		},
	},

	-- ===== Demon Night City =====
	alley_imp = {
		name = "Alley Imp",
		health = 6000,
		coins = 300,
		crystals = 0,
		respawn = 8,
		scale = 0.95,
		style = "Imp",
		body = Color3.fromRGB(150, 30, 60),
		accent = Color3.fromRGB(255, 80, 200),
	},
	lantern_wraith = {
		name = "Lantern Wraith",
		health = 14000,
		coins = 650,
		crystals = 0,
		respawn = 10,
		scale = 1.25,
		style = "Wraith",
		body = Color3.fromRGB(40, 30, 70),
		accent = Color3.fromRGB(80, 220, 255),
	},
	night_fiend = {
		name = "Night Fiend",
		health = 32000,
		coins = 1400,
		crystals = 0,
		respawn = 14,
		scale = 1.5,
		style = "Fiend",
		body = Color3.fromRGB(25, 20, 30),
		accent = Color3.fromRGB(255, 60, 60),
	},
	demon_queen_noctyra = {
		name = "Demon Queen Noctyra",
		health = 300000,
		coins = 80000,
		crystals = 150,
		respawn = 150,
		scale = 3,
		style = "DemonQueen",
		body = Color3.fromRGB(60, 15, 70),
		accent = Color3.fromRGB(255, 50, 160),
		isBoss = true,
		attackInterval = 4,
		attacks = {
			{ displayName = "Hellfire Ring", pattern = "self", telegraph = 1.7, radius = 26, damage = 60 },
			{ displayName = "Shadow Spikes", pattern = "random", count = 9, spread = 28, telegraph = 1.4, radius = 8, damage = 55 },
			{ displayName = "Soul Chains", pattern = "targets", telegraph = 1.3, radius = 11, damage = 55 },
		},
	},
}

-- Точки появи. offset — відносно центру світу (Y = 0 — рівень землі).
-- zone — номер зони з WorldConfig (ворогів закритої зони не можна атакувати).
EnemyConfig.WorldSpawns = {
	NinjaVillage = {
		{ enemy = "bandit_genin", offset = Vector3.new(-22, 0, -65), zone = 1 },
		{ enemy = "bandit_genin", offset = Vector3.new(22, 0, -65), zone = 1 },
		{ enemy = "shadow_puppet", offset = Vector3.new(-38, 0, -15), zone = 1 },
		{ enemy = "shadow_puppet", offset = Vector3.new(38, 0, -15), zone = 1 },
		{ enemy = "rogue_ronin", offset = Vector3.new(-32, 0, 35), zone = 2 },
		{ enemy = "rogue_ronin", offset = Vector3.new(32, 0, 35), zone = 2 },
		{ enemy = "oni_kurogane", offset = Vector3.new(0, 0, 92), zone = 3 },
	},
	PirateIsland = {
		{ enemy = "deckhand_brawler", offset = Vector3.new(-24, 0, -65), zone = 1 },
		{ enemy = "deckhand_brawler", offset = Vector3.new(24, 0, -65), zone = 1 },
		{ enemy = "cannon_crab", offset = Vector3.new(-40, 0, -15), zone = 1 },
		{ enemy = "cannon_crab", offset = Vector3.new(40, 0, -15), zone = 1 },
		{ enemy = "cursed_corsair", offset = Vector3.new(-30, 0, 36), zone = 2 },
		{ enemy = "cursed_corsair", offset = Vector3.new(30, 0, 36), zone = 2 },
		{ enemy = "captain_blackwake", offset = Vector3.new(0, 0, 92), zone = 3 },
	},
	DemonCity = {
		{ enemy = "alley_imp", offset = Vector3.new(-22, 0, -65), zone = 1 },
		{ enemy = "alley_imp", offset = Vector3.new(22, 0, -65), zone = 1 },
		{ enemy = "lantern_wraith", offset = Vector3.new(-36, 0, -15), zone = 1 },
		{ enemy = "lantern_wraith", offset = Vector3.new(36, 0, -15), zone = 1 },
		{ enemy = "night_fiend", offset = Vector3.new(-30, 0, 36), zone = 2 },
		{ enemy = "night_fiend", offset = Vector3.new(30, 0, 36), zone = 2 },
		{ enemy = "demon_queen_noctyra", offset = Vector3.new(0, 0, 92), zone = 3 },
	},
}

return EnemyConfig
]=])

setSource({ "ReplicatedStorage", "Shared", "Config", "HeroConfig" }, "ModuleScript", [=[
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

	{
		id = "marisol_tidecaller",
		name = "Marisol Tidecaller",
		rarity = "Legendary",
		archetype = "Mage",
		element = "Water",
		damage = 118,
		attackSpeed = 1,
		income = 26,
		ability = { name = "Riptide Spiral", description = "Вир затягує ворогів до цілі й сповільнює їх." },
		awakened = { name = "Marisol, Ocean's Voice", multiplier = 3 },
		look = { body = Color3.fromRGB(30, 120, 170), hair = Color3.fromRGB(120, 230, 255), skin = SKIN, height = 1.1 },
	},

	{
		id = "rin_hellbane",
		name = "Rin Hellbane",
		rarity = "Legendary",
		archetype = "Demon Hunter",
		element = "Fire",
		damage = 122,
		attackSpeed = 1.1,
		income = 27,
		ability = { name = "Hellbane Brand", description = "Позначені демони горять і отримують +40% шкоди." },
		awakened = { name = "Rin, Sunfire Exorcist", multiplier = 3 },
		look = { body = Color3.fromRGB(150, 25, 35), hair = Color3.fromRGB(250, 240, 230), skin = SKIN, height = 1.1 },
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

	{
		id = "kaizen_deepcrown",
		name = "Admiral Kaizen Deepcrown",
		rarity = "Mythic",
		archetype = "Pirate",
		element = "Water",
		damage = 345,
		attackSpeed = 1.1,
		income = 84,
		ability = { name = "Leviathan Call", description = "Кличе морського змія, що б'є всіх ворогів на арені." },
		awakened = { name = "Kaizen, Abyss Sovereign", multiplier = 3.3 },
		look = { body = Color3.fromRGB(20, 40, 80), hair = Color3.fromRGB(240, 240, 255), skin = SKIN, height = 1.2 },
	},

	{
		id = "kagura_duskblade",
		name = "Kagura Duskblade",
		rarity = "Mythic",
		archetype = "Demon Hunter",
		element = "Shadow",
		damage = 350,
		attackSpeed = 1.2,
		income = 86,
		ability = { name = "Dusk Requiem", description = "Кожен 3-й удар розрізає тінь цілі: шкода ×3." },
		awakened = { name = "Kagura, Moonless Requiem", multiplier = 3.3 },
		look = { body = Color3.fromRGB(30, 20, 45), hair = Color3.fromRGB(200, 40, 90), skin = SKIN, height = 1.15 },
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
	{
		id = "vael_abyssal",
		name = "Vael, Abyssal Emperor",
		rarity = "Secret",
		archetype = "Swordsman",
		element = "Shadow",
		damage = 1150,
		attackSpeed = 1.1,
		income = 330,
		ability = { name = "Throne of the Abyss", description = "Кожні 10 с поглинає 5% здоров'я всіх ворогів на арені." },
		awakened = { name = "Vael, Endless Abyss", multiplier = 4 },
		look = { body = Color3.fromRGB(15, 10, 25), hair = Color3.fromRGB(160, 60, 255), skin = SKIN, height = 1.3 },
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
]=])

setSource({ "ReplicatedStorage", "Shared", "Config", "QuestConfig" }, "ModuleScript", [=[
-- QuestConfig: завдання та нагороди.
--
-- Main  — сюжетний ланцюжок: одне активне завдання, після нагороди відкривається наступне.
--         metric — що рахуємо (див. GameMath.GetMetric), target — скільки треба.
-- Daily — щоденні завдання: щодня (за UTC) сервер вибирає 3 з пулу.
--         event — подія, яку рахуємо від початку дня: roll, kill, boss, merge, upgrade.
-- reward — { coins = N, crystals = N }

local QuestConfig = {}

QuestConfig.Main = {
	{ id = "first_roll", title = "Перший кидок", description = "Кинь кубик", metric = "totalRolls", target = 1, reward = { coins = 50 } },
	{ id = "builder", title = "Будівничий", description = "Постав 3 героїв на базу", metric = "placedHeroes", target = 3, reward = { coins = 150 } },
	{ id = "collector", title = "Колекціонер", description = "Відкрий 5 різних героїв", metric = "discovered", target = 5, reward = { crystals = 3 } },
	{ id = "squad", title = "Бойовий загін", description = "Збери команду з 3 героїв у ⚔️ Team", metric = "teamSize", target = 3, reward = { coins = 200 } },
	{ id = "first_blood", title = "Перші перемоги", description = "Переможи 5 ворогів у Ninja Village", metric = "enemiesDefeated", target = 5, reward = { crystals = 5 } },
	{ id = "expansion", title = "Розширення бази", description = "Відкрий 5 слотів бази в ⬆️ Upgrades", metric = "slotCount", target = 5, reward = { coins = 500 } },
	{ id = "fire_path", title = "Шлях вогню", description = "Зроби 25 кидків — відкриється Fire Dice", metric = "totalRolls", target = 25, reward = { crystals = 5 } },
	{ id = "dojo", title = "Ворота Dojo", description = "Переможи 15 ворогів — відкриється зона Dojo", metric = "enemiesDefeated", target = 15, reward = { coins = 1000 } },
	{ id = "merge_master", title = "Майстер злиття", description = "Підніми будь-якого героя до 5 рівня (Merge)", metric = "maxHeroLevel", target = 5, reward = { crystals = 10 } },
	{ id = "shrine", title = "Святилище Оні", description = "Переможи 40 ворогів — відкриється арена боса", metric = "enemiesDefeated", target = 40, reward = { crystals = 10 } },
	{ id = "oni_slayer", title = "Переможець Оні", description = "Переможи Oni Warlord Kurogane — відкриється Pirate Island", metric = "boss:oni_kurogane", target = 1, reward = { crystals = 25 } },
	{ id = "landfall", title = "Висадка", description = "Переможи 10 ворогів на Pirate Island", metric = "kills:PirateIsland", target = 10, reward = { crystals = 10 } },
	{ id = "cove", title = "Бухта контрабандистів", description = "20 перемог на острові — відкриється Smugglers' Cove", metric = "kills:PirateIsland", target = 20, reward = { coins = 5000 } },
	{ id = "collector2", title = "Колекціонер II", description = "Відкрий 15 різних героїв", metric = "discovered", target = 15, reward = { crystals = 20 } },
	{ id = "dock", title = "Причал капітана", description = "60 перемог на острові — відкриється Captain's Dock", metric = "kills:PirateIsland", target = 60, reward = { crystals = 15 } },
	{ id = "sea_terror", title = "Гроза морів", description = "Переможи Captain Blackwake — відкриється Tidal Dice", metric = "boss:captain_blackwake", target = 1, reward = { crystals = 60 } },
	{ id = "awakening", title = "Пробудження", description = "Пробуди героя: максимальний рівень + 💎 (Backpack → Awaken)", metric = "awakenedHeroes", target = 1, reward = { crystals = 30 } },
	{ id = "rebirth", title = "Новий початок", description = "Зроби перший ♻️ Rebirth", metric = "rebirths", target = 1, reward = { crystals = 50 } },
	{ id = "night_falls", title = "Настає ніч", description = "Переможи Captain Blackwake — відкриється Demon Night City", metric = "boss:captain_blackwake", target = 1, reward = { crystals = 20 } },
	{ id = "alleys", title = "Темні провулки", description = "Переможи 15 демонів у Demon Night City", metric = "kills:DemonCity", target = 15, reward = { crystals = 15 } },
	{ id = "neon_market", title = "Неоновий ринок", description = "30 перемог у місті — відкриється Neon Market", metric = "kills:DemonCity", target = 30, reward = { coins = 100000 } },
	{ id = "abyss_shrine", title = "Святилище безодні", description = "90 перемог у місті — відкриється Abyss Shrine", metric = "kills:DemonCity", target = 90, reward = { crystals = 30 } },
	{ id = "queen_slayer", title = "Кінець ночі", description = "Переможи Demon Queen Noctyra — відкриється Abyss Dice", metric = "boss:demon_queen_noctyra", target = 1, reward = { crystals = 150 } },
}

QuestConfig.DailyPool = {
	{ id = "d_roll_small", title = "Щоденні кидки", description = "Зроби 20 кидків", event = "roll", target = 20, reward = { coins = 300 } },
	{ id = "d_kill_small", title = "Розминка", description = "Переможи 15 ворогів", event = "kill", target = 15, reward = { coins = 400, crystals = 1 } },
	{ id = "d_merge", title = "Тренування", description = "Злий героїв 2 рази (Merge)", event = "merge", target = 2, reward = { crystals = 2 } },
	{ id = "d_roll_big", title = "Азартний день", description = "Зроби 60 кидків", event = "roll", target = 60, reward = { coins = 800, crystals = 1 } },
	{ id = "d_kill_big", title = "Зачистка села", description = "Переможи 40 ворогів", event = "kill", target = 40, reward = { crystals = 3 } },
	{ id = "d_upgrade", title = "Будівництво", description = "Купи 2 покращення в ⬆️ Upgrades", event = "upgrade", target = 2, reward = { coins = 500 } },
	{ id = "d_boss", title = "Мисливець на босів", description = "Переможи будь-якого боса", event = "boss", target = 1, reward = { crystals = 5 } },
}

QuestConfig.DailyCount = 3

-- Щоденні завдання дня day (номер доби UTC). Однакові для всіх гравців і серверів.
function QuestConfig.GetDaily(day)
	local pool = QuestConfig.DailyPool
	local result = {}
	for i = 0, QuestConfig.DailyCount - 1 do
		table.insert(result, pool[(day + i * 2) % #pool + 1])
	end
	return result
end

-- Нагороди за колекцію: відкрив count різних героїв — забирай кристали.
QuestConfig.CollectionMilestones = {
	{ count = 5, crystals = 5 },
	{ count = 10, crystals = 10 },
	{ count = 15, crystals = 20 },
	{ count = 20, crystals = 40 },
	{ count = 24, crystals = 80 },
	{ count = 27, crystals = 120 },
}

return QuestConfig
]=])

setSource({ "ReplicatedStorage", "Shared", "Config", "WorldConfig" }, "ModuleScript", [=[
-- WorldConfig: світи гри.
-- available — чи можна вже потрапити у світ
-- center    — де світ збудовано (далеко від лобі, у повітрі)
-- unlock    — що потрібно, щоб потрапити у світ: { boss = id боса з EnemyConfig }
-- zones     — зони світу; requiredKills — перемог саме в цьому світі

local WorldConfig = {}

WorldConfig.Order = { "NinjaVillage", "PirateIsland", "DemonCity", "MagicAcademy", "SkyArena" }

WorldConfig.Worlds = {
	NinjaVillage = {
		displayName = "Ninja Village",
		localName = "Село ніндзя",
		description = "Бандити, тіньові ляльки, ронін і бос Oni Warlord Kurogane.",
		color = Color3.fromRGB(90, 230, 140),
		available = true,
		center = Vector3.new(1500, 200, 0),
		-- gateZ — де стоять ворота зони (відносно центру світу).
		zones = {
			{ id = "Outskirts", name = "Outskirts", requiredKills = 0 },
			{ id = "Dojo", name = "Dojo", requiredKills = 15, gateZ = 10 },
			{ id = "OniShrine", name = "Oni Shrine", requiredKills = 40, gateZ = 62 },
		},
	},
	PirateIsland = {
		displayName = "Pirate Island",
		localName = "Острів піратів",
		description = "Матроси, гарматні краби, прокляті корсари й Captain Blackwake.",
		color = Color3.fromRGB(40, 150, 255),
		available = true,
		center = Vector3.new(1500, 200, 1200),
		unlock = { boss = "oni_kurogane" },
		zones = {
			{ id = "Beach", name = "Beach", requiredKills = 0 },
			{ id = "SmugglersCove", name = "Smugglers' Cove", requiredKills = 20, gateZ = 10 },
			{ id = "CaptainsDock", name = "Captain's Dock", requiredKills = 60, gateZ = 62 },
		},
	},
	DemonCity = {
		displayName = "Demon Night City",
		localName = "Нічне місто демонів",
		description = "Вічна ніч, неон, біси, примари та Demon Queen Noctyra.",
		color = Color3.fromRGB(150, 60, 220),
		available = true,
		center = Vector3.new(1500, 200, 2400),
		unlock = { boss = "captain_blackwake" },
		night = true, -- клієнт вмикає нічне освітлення, поки гравець тут
		zones = {
			{ id = "BackAlleys", name = "Back Alleys", requiredKills = 0 },
			{ id = "NeonMarket", name = "Neon Market", requiredKills = 30, gateZ = 10 },
			{ id = "AbyssShrine", name = "Abyss Shrine", requiredKills = 90, gateZ = 62 },
		},
	},
	MagicAcademy = {
		displayName = "Magic Academy",
		localName = "Академія магії",
		description = "Скоро",
		color = Color3.fromRGB(255, 120, 200),
		available = false,
	},
	SkyArena = {
		displayName = "Sky Arena",
		localName = "Небесна арена",
		description = "Скоро",
		color = Color3.fromRGB(255, 230, 120),
		available = false,
	},
}

return WorldConfig
]=])

setSource({ "ReplicatedStorage", "Shared", "GameMath" }, "ModuleScript", [=[
-- GameMath: формули балансу, спільні для сервера й клієнта.
-- Сервер використовує їх для справжніх розрахунків, клієнт — лише для показу,
-- тому цифри в інтерфейсі завжди збігаються з тим, що рахує сервер.

local Config = script.Parent:WaitForChild("Config")
local RarityConfig = require(Config:WaitForChild("RarityConfig"))
local EconomyConfig = require(Config:WaitForChild("EconomyConfig"))
local HeroConfig = require(Config:WaitForChild("HeroConfig"))
local CombatConfig = require(Config:WaitForChild("CombatConfig"))
local ShopConfig = require(Config:WaitForChild("ShopConfig"))
local WorldConfig = require(Config:WaitForChild("WorldConfig"))
local EnemyConfig = require(Config:WaitForChild("EnemyConfig"))

local GameMath = {}

-- Ваги рідкостей з урахуванням удачі кубика та гравця.
function GameMath.GetRarityWeights(dice, playerLuck)
	local luck = dice.luck * (playerLuck or 1)
	local weights = {}
	local total = 0
	for _, rarity in RarityConfig.Order do
		local weight = dice.weights[rarity] or 0
		if RarityConfig.Info[rarity].luckAffected then
			weight *= luck
		end
		weights[rarity] = weight
		total += weight
	end
	return weights, total
end

-- Шанси у відсотках: { Common = 70.1, Rare = 23.0, ... }
function GameMath.GetChances(dice, playerLuck)
	local weights, total = GameMath.GetRarityWeights(dice, playerLuck)
	local chances = {}
	for rarity, weight in weights do
		chances[rarity] = if total > 0 then weight / total * 100 else 0
	end
	return chances
end

-- Шанс випасти саме цьому герою з кубика (0..1) — для напису "1 in 52K".
function GameMath.GetHeroChance(dice, heroId, playerLuck)
	local heroDef = HeroConfig.Heroes[heroId]
	if not heroDef then
		return 0
	end
	local weights, total = GameMath.GetRarityWeights(dice, playerLuck)
	if total <= 0 then
		return 0
	end
	local heroWeight, rarityTotal = 0, 0
	for _, other in HeroConfig.ByRarity[heroDef.rarity] or {} do
		local weight = if dice.element and other.element == dice.element then dice.elementBonus else 1
		rarityTotal += weight
		if other.id == heroId then
			heroWeight = weight
		end
	end
	if rarityTotal <= 0 then
		return 0
	end
	return weights[heroDef.rarity] / total * heroWeight / rarityTotal
end

-- 0.000019 -> "1 in 52.6K"
function GameMath.FormatOdds(chance)
	if chance <= 0 then
		return "1 in ∞"
	end
	return "1 in " .. GameMath.FormatNumber(math.max(1, math.floor(1 / chance + 0.5)))
end

function GameMath.GetIncomeMultiplier(incomeLevel)
	return 1 + (incomeLevel or 0) * EconomyConfig.IncomeUpgrade.bonusPerLevel
end

-- Множник пробудженої форми (1, якщо герой не пробуджений)
function GameMath.GetAwakenMultiplier(heroDef, awakened)
	return if awakened then heroDef.awakened.multiplier else 1
end

function GameMath.GetHeroIncome(heroDef, level, incomeLevel, awakened)
	local levelBonus = 1 + EconomyConfig.LevelIncomeBonus * (level - 1)
	return heroDef.income * levelBonus * GameMath.GetIncomeMultiplier(incomeLevel) * GameMath.GetAwakenMultiplier(heroDef, awakened)
end

function GameMath.GetHeroDamage(heroDef, level, awakened)
	return heroDef.damage * (1 + EconomyConfig.LevelDamageBonus * (level - 1)) * GameMath.GetAwakenMultiplier(heroDef, awakened)
end

function GameMath.GetSellPrice(heroDef, level)
	local base = RarityConfig.Info[heroDef.rarity].sellPrice
	return math.floor(base * (1 + EconomyConfig.SellLevelBonus * (level - 1)))
end

-- Ціна наступного слота або nil, якщо слотів уже максимум.
function GameMath.GetSlotPrice(slotCount)
	if slotCount >= EconomyConfig.MaxSlots then
		return nil
	end
	local upgrade = EconomyConfig.SlotUpgrade
	return math.floor(upgrade.basePrice * upgrade.growth ^ (slotCount - EconomyConfig.StartSlots))
end

-- Ціна наступного рівня доходу або nil, якщо досягнуто максимуму.
function GameMath.GetIncomeUpgradePrice(incomeLevel)
	local upgrade = EconomyConfig.IncomeUpgrade
	if incomeLevel >= upgrade.maxLevel then
		return nil
	end
	return math.floor(upgrade.basePrice * upgrade.growth ^ incomeLevel)
end

-- Номер доби UTC (для щоденних завдань).
function GameMath.GetDay(now)
	return math.floor(now / 86400)
end

-- Чи діє буст ("luck" / "income") у момент now. now = nil — бусти не враховуються.
function GameMath.IsBoostActive(data, boostId, now)
	return now ~= nil and (data.boosts[boostId] or 0) > now
end

function GameMath.GetBoostMultiplier(data, boostId, now)
	if GameMath.IsBoostActive(data, boostId, now) then
		return ShopConfig.Boosts[boostId].multiplier
	end
	return 1
end

-- Серверна подія від адміна ("Luck" / "Income"): множник діє для всіх гравців до часу Event<kind>Ends.
-- Значення лежать в атрибутах workspace, тож їх бачать і сервер, і клієнти. now = nil — подія не враховується.
function GameMath.GetEventMultiplier(kind, now)
	if now == nil then
		return 1
	end
	local multiplier = workspace:GetAttribute("Event" .. kind)
	local ends = workspace:GetAttribute("Event" .. kind .. "Ends")
	if type(multiplier) == "number" and type(ends) == "number" and ends > now and multiplier > 1 then
		return multiplier
	end
	return 1
end

-- Удача гравця (множиться на удачу кубика): зілля × бонус Rebirth × серверна подія.
function GameMath.GetLuck(data, now)
	return GameMath.GetBoostMultiplier(data, "luck", now) * GameMath.GetRebirthLuck(data.rebirths or 0) * GameMath.GetEventMultiplier("Luck", now)
end

function GameMath.GetHeroName(heroDef, awakened)
	return if awakened then heroDef.awakened.name else heroDef.name
end

-- Чи можна пробудити героя. Повертає ok, причина, ціна.
function GameMath.CanAwaken(heroDef, hero)
	local info = RarityConfig.Info[heroDef.rarity]
	if hero.awakened then
		return false, "Герой уже пробуджений", info.awakenCost
	end
	if hero.level < info.maxLevel then
		return false, ("Потрібен максимальний рівень %d (зараз %d)"):format(info.maxLevel, hero.level), info.awakenCost
	end
	return true, nil, info.awakenCost
end

-- Rebirth
function GameMath.GetRebirthCost(rebirths)
	local config = EconomyConfig.Rebirth
	return math.floor(config.baseCost * config.growth ^ rebirths)
end

function GameMath.GetRebirthIncome(rebirths)
	return 1 + rebirths * EconomyConfig.Rebirth.incomeBonus
end

function GameMath.GetRebirthLuck(rebirths)
	return 1 + rebirths * EconomyConfig.Rebirth.luckBonus
end

function GameMath.CountDiscovered(data)
	local count = 0
	for heroId in data.discovered do
		if HeroConfig.Heroes[heroId] then
			count += 1
		end
	end
	return count
end

-- Бонус колекції: +2% доходу за кожного відкритого героя.
function GameMath.GetCollectionMultiplier(data)
	return 1 + GameMath.CountDiscovered(data) * EconomyConfig.CollectionIncomeBonus
end

function GameMath.GetMaxInventory(data)
	return EconomyConfig.MaxInventory + (data.inventoryBonus or 0)
end

-- Ціна наступної "Більшої сумки" або nil, якщо куплено максимум.
function GameMath.GetBagPrice(data)
	local item = ShopConfig.Items.BigBag
	local purchases = math.floor((data.inventoryBonus or 0) / item.amount)
	if purchases >= item.maxPurchases then
		return nil
	end
	return item.basePrice + item.priceStep * purchases
end

-- Скільки ворогів гравець переміг саме в цьому світі.
function GameMath.GetWorldKills(data, worldId)
	return data.worldKills[worldId] or 0
end

function GameMath.GetBossKills(data, enemyId)
	return data.bossKills[enemyId] or 0
end

function GameMath.GetEnemyName(enemyId)
	local def = EnemyConfig.Enemies[enemyId]
	return if def then def.name else tostring(enemyId)
end

-- Чи відкрита зона zoneIndex світу worldId (зони без вимог відкриті завжди).
function GameMath.IsZoneUnlocked(data, worldId, zoneIndex)
	local world = WorldConfig.Worlds[worldId]
	local zone = world and world.zones and world.zones[zoneIndex]
	if not zone then
		return true
	end
	return GameMath.GetWorldKills(data, worldId) >= zone.requiredKills
end

-- Чи можна потрапити у світ. Повертає ok, текст вимоги.
function GameMath.IsWorldUnlocked(data, worldId)
	local world = WorldConfig.Worlds[worldId]
	if not world or not world.available then
		return false, "Скоро"
	end
	local unlock = world.unlock
	if unlock and unlock.boss and GameMath.GetBossKills(data, unlock.boss) < 1 then
		return false, "Переможи " .. GameMath.GetEnemyName(unlock.boss)
	end
	return true, nil
end

-- Чи відкритий кубик. Повертає ok, текст вимоги.
function GameMath.IsDiceUnlocked(data, dice)
	if data.totalRolls < dice.requiredRolls then
		return false, ("%d / %d кидків"):format(data.totalRolls, dice.requiredRolls)
	end
	if dice.requiredBoss and GameMath.GetBossKills(data, dice.requiredBoss) < 1 then
		return false, "Переможи " .. GameMath.GetEnemyName(dice.requiredBoss)
	end
	return true, nil
end

-- Значення для сюжетних завдань (QuestConfig.Main[].metric).
function GameMath.GetMetric(data, metric)
	if metric == "totalRolls" then
		return data.totalRolls
	elseif metric == "slotCount" then
		return data.slotCount
	elseif metric == "discovered" then
		return GameMath.CountDiscovered(data)
	elseif metric == "placedHeroes" then
		local count = 0
		for i = 1, data.slotCount do
			if data.slots[i] ~= "" then
				count += 1
			end
		end
		return count
	elseif metric == "teamSize" then
		local count = 0
		for i = 1, CombatConfig.TeamSize do
			if data.team[i] ~= "" then
				count += 1
			end
		end
		return count
	elseif metric == "rebirths" then
		return data.rebirths or 0
	elseif metric == "awakenedHeroes" then
		local count = 0
		for _, hero in data.heroes do
			if hero.awakened then
				count += 1
			end
		end
		return count
	elseif metric == "maxHeroLevel" then
		local best = 0
		for _, hero in data.heroes do
			best = math.max(best, hero.level)
		end
		return best
	elseif string.sub(metric, 1, 6) == "kills:" then
		return GameMath.GetWorldKills(data, string.sub(metric, 7))
	elseif string.sub(metric, 1, 5) == "boss:" then
		return GameMath.GetBossKills(data, string.sub(metric, 6))
	elseif data.stats[metric] ~= nil then
		return data.stats[metric]
	end
	return 0
end

-- "+300 🪙 +1 💎"
function GameMath.FormatReward(reward)
	local parts = {}
	if reward.coins and reward.coins > 0 then
		table.insert(parts, "+" .. GameMath.FormatNumber(reward.coins) .. " 🪙")
	end
	if reward.crystals and reward.crystals > 0 then
		table.insert(parts, "+" .. GameMath.FormatNumber(reward.crystals) .. " 💎")
	end
	return table.concat(parts, " ")
end

-- 125 -> "2:05"
function GameMath.FormatTime(seconds)
	seconds = math.max(0, math.floor(seconds))
	if seconds >= 3600 then
		return string.format("%d:%02d:%02d", seconds // 3600, (seconds % 3600) // 60, seconds % 60)
	end
	return string.format("%d:%02d", seconds // 60, seconds % 60)
end

-- Загальний дохід бази за секунду з бонусом колекції.
-- now — серверний час; якщо передано, враховується буст доходу.
function GameMath.GetTotalIncome(data, now)
	local total = 0
	for i = 1, data.slotCount do
		local uid = data.slots[i]
		local hero = uid and uid ~= "" and data.heroes[uid]
		local heroDef = hero and HeroConfig.Heroes[hero.id]
		if heroDef then
			total += GameMath.GetHeroIncome(heroDef, hero.level, data.incomeLevel, hero.awakened)
		end
	end
	return total
		* GameMath.GetCollectionMultiplier(data)
		* GameMath.GetRebirthIncome(data.rebirths or 0)
		* GameMath.GetBoostMultiplier(data, "income", now)
		* GameMath.GetEventMultiplier("Income", now)
end

-- Шкода героя за секунду.
function GameMath.GetHeroDps(heroDef, level, awakened)
	return GameMath.GetHeroDamage(heroDef, level, awakened) * heroDef.attackSpeed
end

-- Чи входить герой до бойової команди.
function GameMath.IsInTeam(data, uid)
	for i = 1, CombatConfig.TeamSize do
		if data.team[i] == uid then
			return true
		end
	end
	return false
end

-- Чи стоїть герой на базі.
function GameMath.IsOnBase(data, uid)
	for i = 1, data.slotCount do
		if data.slots[i] == uid then
			return true
		end
	end
	return false
end

-- Сумарна шкода команди за секунду.
function GameMath.GetTeamDps(data)
	local total = 0
	for i = 1, CombatConfig.TeamSize do
		local uid = data.team[i]
		local hero = uid and uid ~= "" and data.heroes[uid]
		local heroDef = hero and HeroConfig.Heroes[hero.id]
		if heroDef then
			total += GameMath.GetHeroDps(heroDef, hero.level, hero.awakened)
		end
	end
	return total
end

-- Скільки кидків лишилось до гарантії кожного рівня.
function GameMath.GetPityRemaining(data)
	local result = {}
	for _, tier in EconomyConfig.Pity do
		local count = data.pity[tier.rarity] or 0
		table.insert(result, { rarity = tier.rarity, remaining = math.max(tier.rolls - count, 1) })
	end
	return result
end

local SUFFIXES = { "", "K", "M", "B", "T", "Qa", "Qi" }

-- 1234 -> "1.23K", 5600000 -> "5.6M"
function GameMath.FormatNumber(value)
	value = tonumber(value) or 0
	if math.abs(value) < 1000 then
		if value == math.floor(value) then
			return tostring(value)
		end
		return string.format("%.1f", value)
	end
	local index = 1
	while math.abs(value) >= 1000 and index < #SUFFIXES do
		value /= 1000
		index += 1
	end
	local text = string.format("%.2f", value):gsub("%.?0+$", "")
	return text .. SUFFIXES[index]
end

function GameMath.FormatChance(percent)
	if percent <= 0 then
		return "—"
	elseif percent < 0.01 then
		return "<0.01%"
	elseif percent < 1 then
		return string.format("%.2f%%", percent)
	end
	return string.format("%.1f%%", percent)
end

return GameMath
]=])

if recording then
	ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
end
print("Частина 1 з 7 готова")
