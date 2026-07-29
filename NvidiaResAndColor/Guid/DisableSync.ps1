###############################################################################
# Copyright (c) 2024 NVIDIA Corporation
###############################################################################
# NAME:    DisableSync.ps1
# REQUIRES: PowerShell 2.0
#
# SYNOPSIS: Отключает синхронизацию для всех дисплеев
#
# DESCRIPTION: Скрипт отключает синхронизацию на всех дисплеях текущей машины.
#              Все дисплеи переводятся в состояние UnSynced.
#              Предназначен для удаленного запуска через PDQ Deploy.
#
###############################################################################

$namespace = "root\CIMV2\NV"
$ErrorActionPreference = "Continue"

# Функция логирования с временными метками
function Write-Log {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"

    switch ($Level) {
        "ERROR"   { Write-Host $logMessage -ForegroundColor Red }
        "WARNING" { Write-Host $logMessage -ForegroundColor Yellow }
        "SUCCESS" { Write-Host $logMessage -ForegroundColor Green }
        default   { Write-Host $logMessage -ForegroundColor White }
    }
}

Write-Log "========================================" "INFO"
Write-Log "Начало выполнения DisableSync.ps1" "INFO"
Write-Log "Hostname: $env:COMPUTERNAME" "INFO"
Write-Log "========================================" "INFO"

try {
    # 1. Получение объекта Sync (карта Quadro Sync)
    Write-Log "Шаг 1: Подключение к WMI namespace: $namespace" "INFO"

    $syncInstances = Get-WmiObject -Namespace $namespace -Class "Sync" -ErrorAction Stop

    if (-not $syncInstances) {
        Write-Log "ПРЕДУПРЕЖДЕНИЕ: Sync-устройство не найдено!" "WARNING"
        Write-Log "Возможно, синхронизация уже отключена или устройство не установлено" "WARNING"
        Write-Log "Завершение работы (нечего отключать)" "INFO"
        exit 0
    }

    $sync = [System.Management.ManagementObject]$syncInstances
    Write-Log "Sync-устройство найдено успешно" "SUCCESS"
    Write-Log "  ID устройства: $($sync.id)" "INFO"
    Write-Log "  Имя устройства: $($sync.name)" "INFO"
    Write-Log "  Уникальное имя: $($sync.uname)" "INFO"

    # 2. Проверка текущего состояния синхронизации
    Write-Log "Шаг 2: Проверка текущего состояния синхронизации" "INFO"
    Write-Log "  Текущий статус isSynced: $($sync.isSynced)" "INFO"
    Write-Log "  Текущий статус isStereoSynced: $($sync.isStereoSynced)" "INFO"

    if ($sync.isSynced -eq $false) {
        Write-Log "Синхронизация уже отключена" "INFO"
        Write-Log "Продолжаем для гарантированного сброса всех дисплеев..." "INFO"
    } else {
        Write-Log "Обнаружена активная синхронизация - будет отключена" "INFO"
    }

    # 3. Получение списка дисплеев
    Write-Log "Шаг 3: Получение списка дисплеев для отключения синхронизации" "INFO"

    if (-not $sync.syncDisplays -or $sync.syncDisplays.Count -eq 0) {
        Write-Log "ПРЕДУПРЕЖДЕНИЕ: Нет дисплеев в syncDisplays" "WARNING"
        Write-Log "Возможно, дисплеи уже отключены от синхронизации" "WARNING"
        Write-Log "Завершение работы" "INFO"
        exit 0
    }

    Write-Log "Найдено дисплеев в syncDisplays: $($sync.syncDisplays.Count)" "INFO"

    # 4. Извлечение ID дисплеев и подготовка массивов
    $syncDisplayIds = @()
    $syncStates = @()
    $displayCount = 0

    foreach ($displayStr in $sync.syncDisplays) {
        Write-Log "  Обработка: $displayStr" "INFO"

        # Извлекаем ID из строки вида "SyncTopology.id=1001"
        if ($displayStr -match "id=(\d+)") {
            $id = [int]$matches[1]
            $syncDisplayIds += $id
            $syncStates += 0  # 0 = UnSynced (отключено)
            $displayCount++

            Write-Log "    Дисплей ID: $id -> будет установлен как UNSYNCED" "INFO"
        } else {
            Write-Log "    ПРЕДУПРЕЖДЕНИЕ: Не удалось извлечь ID из '$displayStr'" "WARNING"
        }
    }

    if ($displayCount -eq 0) {
        Write-Log "ПРЕДУПРЕЖДЕНИЕ: Не удалось извлечь ID ни одного дисплея!" "WARNING"
        Write-Log "Завершение работы" "INFO"
        exit 0
    }

    Write-Log "Подготовлено дисплеев для отключения: $displayCount" "SUCCESS"

    # 5. Применение настроек синхронизации (отключение)
    Write-Log "Шаг 4: Отключение синхронизации для всех дисплеев" "INFO"

    $method = "setSyncStateById"
    $params = $sync.GetMethodParameters($method)

    if (-not $params) {
        Write-Log "КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить параметры метода $method" "ERROR"
        exit 1
    }

    $params.syncDisplayIds = $syncDisplayIds
    $params.syncState = $syncStates

    Write-Log "  Вызов метода: $method" "INFO"
    Write-Log "  Параметры:" "INFO"
    Write-Log "    syncDisplayIds: $($syncDisplayIds -join ', ')" "INFO"
    Write-Log "    syncState: $($syncStates -join ', ') (0=UnSynced)" "INFO"

    $result = $sync.InvokeMethod($method, $params, $null)

    # 6. Проверка результата
    Write-Log "Шаг 5: Проверка результата выполнения" "INFO"

    if ($result.ReturnValue -eq $true) {
        Write-Log "========================================" "SUCCESS"
        Write-Log "УСПЕХ! Синхронизация отключена" "SUCCESS"
        Write-Log "========================================" "SUCCESS"
        Write-Log "Все дисплеи ($displayCount шт.) переведены в режим UNSYNCED" "SUCCESS"
        Write-Log "Дисплеи ID: $($syncDisplayIds -join ', ')" "SUCCESS"

        # Дополнительная проверка состояния
        $syncRefresh = Get-WmiObject -Namespace $namespace -Class "Sync"
        if ($syncRefresh) {
            Write-Log "Финальный статус isSynced: $($syncRefresh.isSynced)" "INFO"

            if ($syncRefresh.isSynced -eq $false) {
                Write-Log "Подтверждено: синхронизация полностью отключена" "SUCCESS"
            } else {
                Write-Log "ВНИМАНИЕ: isSynced все еще True - возможна задержка обновления" "WARNING"
            }
        }

        exit 0
    } else {
        Write-Log "========================================" "ERROR"
        Write-Log "ОШИБКА при отключении синхронизации!" "ERROR"
        Write-Log "========================================" "ERROR"
        Write-Log "ReturnValue метода: $($result.ReturnValue)" "ERROR"
        Write-Log "Возможные причины:" "ERROR"
        Write-Log "  - Дисплеи заблокированы другим процессом" "ERROR"
        Write-Log "  - Конфликт с настройками Sync" "ERROR"
        Write-Log "  - Аппаратная проблема с Sync-картой" "ERROR"
        exit 1
    }

} catch {
    Write-Log "========================================" "ERROR"
    Write-Log "КРИТИЧЕСКОЕ ИСКЛЮЧЕНИЕ!" "ERROR"
    Write-Log "========================================" "ERROR"
    Write-Log "Сообщение: $($_.Exception.Message)" "ERROR"
    Write-Log "Строка: $($_.InvocationInfo.ScriptLineNumber)" "ERROR"
    Write-Log "Команда: $($_.InvocationInfo.Line.Trim())" "ERROR"

    if ($_.Exception.InnerException) {
        Write-Log "Внутреннее исключение: $($_.Exception.InnerException.Message)" "ERROR"
    }

    Write-Log "StackTrace:" "ERROR"
    Write-Log "$($_.ScriptStackTrace)" "ERROR"

    exit 1
}
