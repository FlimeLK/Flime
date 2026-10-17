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
