-- AdminConfig: хто має доступ до адмін-панелі.
-- Кожну дію адміна сервер перевіряє заново — клієнт лише показує кнопки.

local AdminConfig = {}

-- Імена адмінів. Сервер сам перетворює їх на UserId (так надійніше, ніж порівнювати імена).
AdminConfig.Usernames = { "FlimeYTLK" }

-- UserId адмінів (необов'язково): числа з посилання на профіль roblox.com/users/<UserId>/profile
AdminConfig.UserIds = {}

-- Власник гри (або власник групи, якщо гра групова) — завжди адмін
AdminConfig.OwnerIsAdmin = true

-- У Studio (Play / Start Server) адмінами є всі тестові гравці — зручно перевіряти панель
AdminConfig.StudioIsAdmin = true

-- Межі, щоб випадковий нуль зайвий не зламав економіку
AdminConfig.MaxCurrency = 1e15
AdminConfig.MaxHeroesPerAction = 10
AdminConfig.MaxBoostMinutes = 24 * 60
AdminConfig.MaxEventMinutes = 120
AdminConfig.EventMultipliers = { 2, 3, 5, 10 }
AdminConfig.WalkSpeeds = { 16, 32, 60, 100 }
AdminConfig.LogSize = 60

return AdminConfig
