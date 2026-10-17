-- WorldConfig: світи гри. На етапі 1 портали в лобі декоративні,
-- бої та вороги з'являться на етапі 2 (спершу лише "Ninja Village").

local WorldConfig = {}

WorldConfig.Order = { "NinjaVillage", "PirateIsland", "DemonCity", "MagicAcademy", "SkyArena" }

WorldConfig.Worlds = {
	NinjaVillage = {
		displayName = "Ninja Village",
		localName = "Село ніндзя",
		color = Color3.fromRGB(90, 230, 140),
		available = false, -- стане true на етапі 2
	},
	PirateIsland = {
		displayName = "Pirate Island",
		localName = "Острів піратів",
		color = Color3.fromRGB(40, 150, 255),
		available = false,
	},
	DemonCity = {
		displayName = "Demon Night City",
		localName = "Нічне місто демонів",
		color = Color3.fromRGB(150, 60, 220),
		available = false,
	},
	MagicAcademy = {
		displayName = "Magic Academy",
		localName = "Академія магії",
		color = Color3.fromRGB(255, 120, 200),
		available = false,
	},
	SkyArena = {
		displayName = "Sky Arena",
		localName = "Небесна арена",
		color = Color3.fromRGB(255, 230, 120),
		available = false,
	},
}

return WorldConfig
