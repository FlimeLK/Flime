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

-- Портрети героїв (картинка, яка показується під час кидка, у Backpack, Team та Index).
-- Використовуй лише картинки, на які маєш права: власний арт, куплений арт-пак
-- або безкоштовний пак, що дозволяє використання в іграх. Порожньо — показується 3D-модель.
AssetConfig.HeroPortraits = {
	riku_windstep = "", -- Riku Windstep (Common)
	tomo_deckhand = "", -- Tomo the Deckhand (Common)
	hana_emberling = "", -- Hana Emberling (Common)
	zen_cadet = "", -- Zen Star Cadet (Common)
	shiro_quickblade = "", -- Shiro Quickblade (Rare)
	kaito_saltfang = "", -- Kaito Saltfang (Rare)
	mira_cinderveil = "", -- Mira Cinderveil (Rare)
	yoru_lantern = "", -- Yoru Lanternbearer (Rare)
	akane_crimsonfan = "", -- Akane Crimson Fan (Epic)
	raizo_thunderstep = "", -- Raizo Thunderstep (Epic)
	nox_hollowhunter = "", -- Nox Hollowhunter (Epic)
	coral_vex = "", -- Captain Coral Vex (Epic)
	seren_starblade = "", -- Seren Starblade (Legendary)
	kuro_moonreaper = "", -- Kuro Moonreaper (Legendary)
	homura_ashcrown = "", -- Homura Ashcrown (Legendary)
	ryo_skybolt = "", -- Ryo Skybolt (Legendary)
	marisol_tidecaller = "", -- Marisol Tidecaller (Legendary)
	rin_hellbane = "", -- Rin Hellbane (Legendary)
	astra_novaempress = "", -- Astra, Nova Empress (Mythic)
	gekko_voidshinobi = "", -- Gekko the Void Shinobi (Mythic)
	volta_stormcaptain = "", -- Storm Captain Volta (Mythic)
	ifra_phoenixsaint = "", -- Ifra, Phoenix Saint (Mythic)
	kaizen_deepcrown = "", -- Admiral Kaizen Deepcrown (Mythic)
	kagura_duskblade = "", -- Kagura Duskblade (Mythic)
	solenne_eclipse = "", -- Solenne, Eclipse Sovereign (Secret)
	mugen_dicegod = "", -- Mugen, the Dice God (Secret)
	vael_abyssal = "", -- Vael, Abyssal Emperor (Secret)
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

function AssetConfig.GetPortrait(heroId)
	return normalize(AssetConfig.HeroPortraits[heroId])
end

function AssetConfig.GetSound(key)
	return normalize(AssetConfig.Sounds[key])
end

return AssetConfig
