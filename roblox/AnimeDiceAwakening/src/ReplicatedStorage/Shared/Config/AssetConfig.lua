-- AssetConfig: картинки (іконки) і звуки гри.
--
-- Іконки лежать у репозиторії: assets/icons/*.png (власний набір гри, можна вільно
-- використовувати). Завантаж їх у Roblox (Asset Manager → Bulk Import),
-- скопіюй ID кожної та встав сюди: "rbxassetid://1234567890" або просто "1234567890".
--
-- Поки поле порожнє (""), гра показує емодзі — нічого не ламається.
-- Звуки так само: Toolbox → Audio → права кнопка → Copy Asset ID.

local AssetConfig = {}

AssetConfig.Icons = {
	-- Головний екран
	Roll = "",
	Backpack = "",
	Team = "",
	Upgrades = "",
	Quests = "",
	Rebirth = "",
	Index = "",
	Worlds = "",
	Home = "",
	Shop = "",
	Settings = "",
	Auto = "",
	Lock = "",
	-- Валюти й удача
	Coin = "",
	Crystal = "",
	Luck = "",
	-- Магазин і покращення
	Slots = "",
	Income = "",
	LuckPotion = "",
	CoinPotion = "",
	BigBag = "",
}

-- Емодзі, які показуються, поки картинку не підключено
AssetConfig.Fallback = {
	Roll = "🎲",
	Backpack = "🎒",
	Team = "⚔️",
	Upgrades = "⬆️",
	Quests = "📜",
	Rebirth = "♻️",
	Index = "📖",
	Worlds = "🌍",
	Home = "🏠",
	Shop = "🛒",
	Settings = "⚙️",
	Auto = "🔄",
	Lock = "🔒",
	Coin = "🪙",
	Crystal = "💎",
	Luck = "🍀",
	Slots = "🧱",
	Income = "💰",
	LuckPotion = "🍀",
	CoinPotion = "💰",
	BigBag = "🎒",
}

AssetConfig.Sounds = {
	Click = "", -- натискання кнопки
	RollTick = "", -- кожна зміна героя під час прокрутки
	Reveal = "", -- випав герой
	RareReveal = "", -- випав Legendary і рідкісніший
	Purchase = "", -- успішна покупка
	Reward = "", -- нагорода (завдання, бос)
	Error = "", -- помилка / не вистачає монет
}

AssetConfig.SoundVolume = {
	Click = 0.4,
	RollTick = 0.3,
	Reveal = 0.7,
	RareReveal = 0.9,
	Purchase = 0.6,
	Reward = 0.7,
	Error = 0.5,
}

local function normalize(id)
	if type(id) ~= "string" or id == "" then
		return nil
	end
	if string.match(id, "^%d+$") then
		return "rbxassetid://" .. id
	end
	return id
end

-- Повна адреса картинки або nil, якщо її ще не підключено.
function AssetConfig.GetImage(key)
	return normalize(AssetConfig.Icons[key])
end

function AssetConfig.GetSound(key)
	return normalize(AssetConfig.Sounds[key])
end

return AssetConfig
