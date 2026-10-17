-- WorldConfig: світи гри.
-- available — чи можна вже потрапити у світ
-- center    — де світ збудовано (далеко від лобі, у повітрі)

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
	},
	PirateIsland = {
		displayName = "Pirate Island",
		localName = "Острів піратів",
		description = "Скоро",
		color = Color3.fromRGB(40, 150, 255),
		available = false,
	},
	DemonCity = {
		displayName = "Demon Night City",
		localName = "Нічне місто демонів",
		description = "Скоро",
		color = Color3.fromRGB(150, 60, 220),
		available = false,
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
