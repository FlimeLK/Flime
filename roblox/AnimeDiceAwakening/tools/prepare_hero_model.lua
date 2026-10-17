-- Готує модель з Toolbox для героя. Запускати в Studio: View/Window → Command Bar.
--
-- 1. Встав модель з Toolbox (вона з'явиться у Workspace).
-- 2. Виділи її в Explorer.
-- 3. Нижче впиши id героя з Config/HeroConfig (наприклад "seren_starblade").
-- 4. Скопіюй увесь цей текст у Command Bar і натисни Enter.
--
-- Скрипт видалить з моделі ВСІ скрипти й звуки (у безкоштовних моделях часто бувають
-- шкідливі "backdoor"-скрипти), перейменує її та перенесе в ReplicatedStorage/HeroModels.

local HERO_ID = "seren_starblade"

local Selection = game:GetService("Selection")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local model = Selection:Get()[1]
if not model or not model:IsA("Model") then
	warn("Виділи модель у Explorer")
	return
end

local removed = 0
for _, descendant in model:GetDescendants() do
	if descendant:IsA("BaseScript") or descendant:IsA("ModuleScript") or descendant:IsA("Sound") then
		descendant:Destroy()
		removed += 1
	end
end

local folder = ReplicatedStorage:FindFirstChild("HeroModels")
if not folder then
	folder = Instance.new("Folder")
	folder.Name = "HeroModels"
	folder.Parent = ReplicatedStorage
end
local old = folder:FindFirstChild(HERO_ID)
if old then
	old:Destroy()
end
model.Name = HERO_ID
model.Parent = folder
Selection:Set({ model })
print(("✅ Модель готова для %s. Видалено скриптів/звуків: %d"):format(HERO_ID, removed))
