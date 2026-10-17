-- EnemyConfig: вороги, боси та де вони з'являються у кожному світі.
-- health   — запас здоров'я
-- coins    — нагорода в Coins кожному, хто допоміг перемогти
-- crystals — нагорода в Crystals (лише боси)
-- respawn  — через скільки секунд ворог з'явиться знову
-- style    — зовнішній вигляд простої моделі з Part

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
			GroundSlam = { displayName = "Ground Slam", telegraph = 1.6, radius = 20, damage = 35 },
			-- Дощ сюрикенів: кола під кожним гравцем поруч, треба відбігти
			ShurikenRain = { displayName = "Shuriken Rain", telegraph = 1.3, radius = 9, damage = 25 },
		},
	},
}

-- Точки появи. offset — відносно центру світу (Y = 0 — рівень землі).
EnemyConfig.WorldSpawns = {
	NinjaVillage = {
		{ enemy = "bandit_genin", offset = Vector3.new(-22, 0, -65) },
		{ enemy = "bandit_genin", offset = Vector3.new(22, 0, -65) },
		{ enemy = "shadow_puppet", offset = Vector3.new(-38, 0, -15) },
		{ enemy = "shadow_puppet", offset = Vector3.new(38, 0, -15) },
		{ enemy = "rogue_ronin", offset = Vector3.new(-32, 0, 35) },
		{ enemy = "rogue_ronin", offset = Vector3.new(32, 0, 35) },
		{ enemy = "oni_kurogane", offset = Vector3.new(0, 0, 92) },
	},
}

return EnemyConfig
