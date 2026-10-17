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
		center = Vector3.new(1500, 200, 500),
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
		center = Vector3.new(1500, 200, 1000),
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
