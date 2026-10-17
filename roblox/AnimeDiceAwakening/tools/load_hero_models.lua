-- Завантажує готові моделі з Creator Store (Toolbox) для героїв — одним запуском.
-- Запускати в Studio: Command Bar (рядок унизу) → встав увесь текст → Enter.
--
-- Для кожного героя скрипт:
--   1. завантажує модель за ID (як вставка з Toolbox),
--   2. видаляє з неї ВСІ скрипти й звуки (захист від шкідливих "backdoor"),
--   3. кладе в ReplicatedStorage/HeroModels з назвою героя.
-- Гра сама масштабує модель і ставить її на слот (див. HeroModelBuilder).
--
-- Можеш змінити будь-який ID на свій або видалити рядок — тоді герой лишиться
-- з простою моделлю з деталей.

-- Моделі підібрані за класом і стихією героя: безкоштовні, без персонажів чужих франшиз.
-- Прев'ю всіх: docs/hero-models.png
local MODELS = {
	riku_windstep = 1073102214, -- Riku Windstep (Common)
	tomo_deckhand = 100944702942220, -- Tomo the Deckhand (Common)
	hana_emberling = 6024404244, -- Hana Emberling (Common)
	zen_cadet = 11272270678, -- Zen Star Cadet (Common)
	shiro_quickblade = 15560466932, -- Shiro Quickblade (Rare)
	kaito_saltfang = 132434304646924, -- Kaito Saltfang (Rare)
	mira_cinderveil = 10559568125, -- Mira Cinderveil (Rare)
	yoru_lantern = 136347862663720, -- Yoru Lanternbearer (Rare)
	akane_crimsonfan = 12306246169, -- Akane Crimson Fan (Epic)
	raizo_thunderstep = 3162408043, -- Raizo Thunderstep (Epic)
	nox_hollowhunter = 126153895579904, -- Nox Hollowhunter (Epic)
	coral_vex = 799516341, -- Captain Coral Vex (Epic)
	seren_starblade = 8073321485, -- Seren Starblade (Legendary)
	kuro_moonreaper = 133610989566243, -- Kuro Moonreaper (Legendary)
	homura_ashcrown = 5123918805, -- Homura Ashcrown (Legendary)
	ryo_skybolt = 11755051899, -- Ryo Skybolt (Legendary)
	marisol_tidecaller = 15485406525, -- Marisol Tidecaller (Legendary)
	rin_hellbane = 631606520, -- Rin Hellbane (Legendary)
	astra_novaempress = 12229211926, -- Astra, Nova Empress (Mythic)
	gekko_voidshinobi = 92307562986867, -- Gekko the Void Shinobi (Mythic)
	volta_stormcaptain = 3552939059, -- Storm Captain Volta (Mythic)
	ifra_phoenixsaint = 79118375438271, -- Ifra, Phoenix Saint (Mythic)
	kaizen_deepcrown = 10854041153, -- Admiral Kaizen Deepcrown (Mythic)
	kagura_duskblade = 8829461349, -- Kagura Duskblade (Mythic)
	solenne_eclipse = 7084656859, -- Solenne, Eclipse Sovereign (Secret)
	mugen_dicegod = 114744297, -- Mugen, the Dice God (Secret)
	vael_abyssal = 121497881801826, -- Vael, Abyssal Emperor (Secret)
}

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local folder = ReplicatedStorage:FindFirstChild("HeroModels")
if not folder then
	folder = Instance.new("Folder")
	folder.Name = "HeroModels"
	folder.Parent = ReplicatedStorage
end

-- Знаходить у завантаженому першу модель-персонажа (з Humanoid), або будь-яку модель
local function pickCharacter(objects)
	local fallback = nil
	for _, object in objects do
		local candidates = { object }
		for _, descendant in object:GetDescendants() do
			table.insert(candidates, descendant)
		end
		for _, candidate in candidates do
			if candidate:IsA("Model") then
				if candidate:FindFirstChildOfClass("Humanoid") then
					return candidate
				end
				fallback = fallback or candidate
			end
		end
	end
	return fallback
end

local loaded, failed = 0, 0
for heroId, assetId in MODELS do
	local ok, objects = pcall(function()
		return game:GetObjects("rbxassetid://" .. assetId)
	end)
	local model = ok and pickCharacter(objects)
	if model then
		-- Модель переносимо (а не копіюємо): частина моделей з Toolbox не дозволяє Clone
		for _, descendant in model:GetDescendants() do
			if descendant:IsA("BaseScript") or descendant:IsA("ModuleScript") or descendant:IsA("Sound") then
				descendant:Destroy()
			end
		end
		local old = folder:FindFirstChild(heroId)
		if old then
			old:Destroy()
		end
		model.Name = heroId
		model.Parent = folder
		loaded += 1
		print(("✅ %s ← %d"):format(heroId, assetId))
	else
		failed += 1
		warn(("❌ %s: не вдалося завантажити модель %d"):format(heroId, assetId))
	end
	-- Решта завантаженого (якщо це був пак) не потрапляє в гру
	if ok then
		for _, object in objects do
			if object ~= model and object.Parent ~= folder then
				object:Destroy()
			end
		end
	end
end
print(("Готово: %d моделей, помилок: %d"):format(loaded, failed))
