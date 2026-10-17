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
