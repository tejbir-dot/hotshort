/**
 * Facebook Early Interceptor - Readable Version
 * 用于拦截和捕获Facebook广告库数据的脚本
 * 
 * 主要功能：
 * 1. 劫持XMLHttpRequest来拦截Facebook广告库的API请求
 * 2. 提取和存储广告数据、认证令牌等信息
 * 3. 对数据进行标准化处理和去重
 */

(function () {
    "use strict";

    // 初始化全局数据存储对象
    window.__denote_captured_data = {
        ads: [],                // 存储捕获的广告数据
        sessionID: null,        // 会话ID
        X_FB_LSD: null,        // Facebook安全令牌
        X_ASBD_ID: null,       // Facebook另一个安全标识
        requestBody: null,      // 请求体数据
        req: null,             // 请求序号
        s: null,               // 会话标识
        doc_id: null,          // 文档ID
        totalCount: 0          // 广告总数量
    };

    // 全局数据获取状态管理
    if (!window.__denote_data_collection_state || !window.__denote_captured_data.ads.length) {
        window.__denote_data_collection_state = {
            hasData: false,
            sources: {
                xhr: false,
                dom: false,
                script: false
            },
            stopCollection: false
        };
    }

    // 全局配置变量
    let extConfig = null;

    // 立即注册事件监听器，确保在事件分发前注册
    function handleEarlyConfigEvent(event) {
        console.log('Early handleConfigEvent: Event received:', event.type, event.detail);
        if (event.type === '[Denote]page-rules' && event.detail) {
            const rule = event.detail.filter(it => it.platform === '5')[0]?.rule;
            console.log('Early received config:', rule);
            extConfig = rule?.earlyInterceptor || getFallbackConfig();
            document.body.removeEventListener('[Denote]page-rules', handleEarlyConfigEvent);
        }
    }

    // 立即添加事件监听器
    document.body?.addEventListener('[Denote]page-rules', handleEarlyConfigEvent);

    // 获取扩展配置（优化版本）
    async function getExtensionConfig() {
        // 如果已经有配置，直接返回
        if (extConfig) {
            console.log('getExtensionConfig: Using cached config:', extConfig);
            return extConfig;
        }

        try {
            // 等待早期监听器获取配置，或者超时后使用后备方案
            return new Promise((resolve) => {
                const checkInterval = 100; // 每100ms检查一次
                const maxWaitTime = 3000;  // 最多等待3秒
                let elapsedTime = 0;

                const checkTimer = setInterval(() => {
                    elapsedTime += checkInterval;

                    // 如果早期监听器已经获取到配置
                    if (extConfig) {
                        clearInterval(checkTimer);
                        resolve(extConfig);
                        return;
                    }

                    // 如果超时，使用后备配置
                    if (elapsedTime >= maxWaitTime) {
                        extConfig = getFallbackConfig();
                        clearInterval(checkTimer);
                        resolve(extConfig);
                    }
                }, checkInterval);

                // 立即检查一次，避免不必要的等待
                if (extConfig) {
                    clearInterval(checkTimer);
                    resolve(extConfig);
                }
            });
        } catch (error) {
            console.log('getExtensionConfig: Error occurred, using fallback:', error);
            extConfig = getFallbackConfig();
            return extConfig;
        }
    }

    // 默认配置（作为后备方案）
    function getFallbackConfig() {
        return {
            searchKeywords: ['search_results_connection', 'page_info'],
            scriptSelectors: ['script[type="application/json"]', 'script:not([src])'],
            dataStructures: {
                searchResultsConnection: 'search_results_connection',
                pageInfo: 'page_info'
            }
        };
    }

    // 检查是否已有数据的函数
    function hasAnyData() {
        return window.__denote_captured_data && window.__denote_captured_data.ads.length > 0;
    }

    // 标记数据获取成功的函数
    function markDataCollected(source) {
        if (!window.__denote_data_collection_state) return;

        window.__denote_data_collection_state.hasData = true;
        window.__denote_data_collection_state.sources[source] = true;
        window.__denote_data_collection_state.stopCollection = true;

        console.log(`Data collection successful via ${source}, stopping other collection methods`);

        // 发送自定义事件通知内容脚本
        dispatchDataEvent();
    }

    // 检查是否应该停止数据收集
    function shouldStopCollection() {
        return window.__denote_data_collection_state &&
            window.__denote_data_collection_state.stopCollection;
    }

    // 发送自定义事件，将数据传递给内容脚本
    function dispatchDataEvent() {
        try {
            const adsCount = window.__denote_captured_data?.ads?.length || 0;
            const totalCount = window.__denote_captured_data?.totalCount || 0;
            
            console.log(`Dispatching data event: ${adsCount} ads captured, total count: ${totalCount}`);
            
            const eventData = {
                type: 'denote_ads_data_captured',
                data: window.__denote_captured_data,
                source: window.__denote_data_collection_state.source,
                timestamp: Date.now()
            };

            // 创建自定义事件
            const customEvent = new CustomEvent('denote_ads_data_ready', {
                detail: eventData,
                bubbles: true,
                cancelable: true
            });

            // 分发事件到document
            document.dispatchEvent(customEvent);
            console.log('Custom event dispatched to document');

            // 也可以通过postMessage发送到window
            window.postMessage({
                type: 'DENOTE_ADS_DATA',
                payload: eventData
            }, '*');
            console.log('PostMessage sent to window');

        } catch (error) {
            console.error('Error dispatching custom event:', error);
        }
    }

    // 监听来自内容脚本的请求，按需返回当前已捕获的数据
    window.addEventListener('message', function (event) {
        try {
            const msg = event && event.data;
            if (!msg || !msg.type) return;

            // 内容脚本主动请求当前数据（用于错过早期事件的情况）
            if (msg.type === 'DN_REQUEST_ADS_DATA') {
                const eventData = {
                    type: 'denote_ads_data_captured',
                    data: window.__denote_captured_data,
                    source: 'request',
                    timestamp: Date.now()
                };
                window.postMessage({
                    type: 'DENOTE_ADS_DATA',
                    payload: eventData
                }, '*');
            }
        } catch (e) {
            console.error('Early interceptor message handling error:', e);
        }
    });

    // 保存原始的方法
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;
    const originalSend = XMLHttpRequest.prototype.send;
    const originalFetch = window.fetch;

    /**
     * 第二种方式： 重写XMLHttpRequest.open方法 TODO: 响应数据待完善
     */
    XMLHttpRequest.prototype.open = function(method, url, ...args) {
        this._method = method;
        this._url = url;
        this._headers = {};
        originalOpen.apply(this, [method, url, ...args]);
    };

    /**
     * 第二种方式： 重写XMLHttpRequest.setRequestHeader方法 TODO: 响应数据待完善
     */
    XMLHttpRequest.prototype.setRequestHeader = function(header, value) {
        this._headers[header] = value;
        originalSetRequestHeader.apply(this, [header, value]);
    };

    /**
     * 第二种方式： 重写XMLHttpRequest.send方法 - 核心拦截逻辑
     */
    XMLHttpRequest.prototype.send = function(data) {
        this._data = data;

        // 添加响应监听器
        this.addEventListener("load", function() {

            // 只处理Facebook广告库页面的请求（放宽匹配条件）
            if (!location.href.includes("facebook.com/ads/library")) {
                console.log('Request filtered out - not ad library page:', {
                    url: this._url,
                    location: location.href
                });
                return;
            }

            // 检查是否为Facebook API请求（扩展支持的端点）
            const isFacebookApiRequest = 
                this._url === "/api/graphql" ||
                this._url === "/api/graphql/" ||           // 原始GraphQL端点
                this._url.startsWith("/ajax/bz") ||        // 新的bz端点
                this._url.includes("/ajax/bootloader") ||  // bootloader端点
                this._url.includes("/api/") ||             // 其他API端点
                this._url.includes("graphql");             // 任何包含graphql的端点

            if (!isFacebookApiRequest) {
                console.log('Request filtered out - not Facebook API:', {
                    url: this._url,
                    location: location.href,
                    isAdLibrary: true,
                    isFacebookApi: false
                });
                return;
            }

            console.log('Facebook API request detected:', {
                url: this._url,
                location: location.href,
                isAdLibrary: true,
                isFacebookApi: true
            });

            console.log('URL conditions met, processing response...');

            // 提取Facebook安全令牌
            if (this._headers["X-FB-LSD"]) {
                window.__denote_captured_data.X_FB_LSD = this._headers["X-FB-LSD"];
            }
            if (this._headers["X-ASBD-ID"]) {
                window.__denote_captured_data.X_ASBD_ID = this._headers["X-ASBD-ID"];
            }

            // 解析请求数据
             let parsedData = {};
             let hasValidRequestData = false;

             try {
                 // 尝试解析URL编码的表单数据
                 if (this._data && typeof this._data === 'string' && this._data.includes('=')) {
                     // 使用URLSearchParams来正确解析表单数据
                     const urlParams = new URLSearchParams(this._data);
                     parsedData = {};
                     for (const [key, value] of urlParams) {
                         parsedData[key] = value;
                     }
                     hasValidRequestData = true;
                     console.log('Parsed form data successfully, fb_api_req_friendly_name:', parsedData.fb_api_req_friendly_name);
                 } else if (this._data) {
                     // 尝试直接解析JSON数据
                     try {
                         parsedData = JSON.parse(this._data);
                         hasValidRequestData = true;
                         console.log('Parsed JSON data successfully');
                     } catch (jsonError) {
                         console.log('Data is not JSON format, continuing with empty parsedData');
                     }
                 }
             } catch (error) {
                 console.log('Failed to parse request data, continuing with empty parsedData:', error);
             }

            // 如果有有效的请求数据，更新相关字段
            if (hasValidRequestData && parsedData.__req) {
                window.__denote_captured_data.req = (parseInt(parsedData.__req, 36) + 1).toString(36);
            }
            if (hasValidRequestData && parsedData.__s) {
                window.__denote_captured_data.s = parsedData.__s;
            }

            // 尝试提取会话ID
            if (hasValidRequestData && parsedData.variables) {
                try {
                    let variables = JSON.parse(parsedData.variables);
                    if (variables.session_id) {
                        window.__denote_captured_data.sessionID = variables.session_id;
                    }
                    if (variables.sessionId) {
                        window.__denote_captured_data.sessionID = variables.sessionId;
                    }
                    if (variables.sessionID) {
                        window.__denote_captured_data.sessionID = variables.sessionID;
                    }
                } catch (error) {
                    // 忽略解析错误
                }
            }

            // 处理广告详情查询的文档ID
            if (hasValidRequestData && parsedData.fb_api_req_friendly_name === "AdLibraryAdDetailsV2Query" && 
                !window.__denote_captured_data.doc_id) {
                window.__denote_captured_data.doc_id = parsedData.doc_id;
            }

            // 构建请求体数据（如果有有效数据）
            if (hasValidRequestData) {
                window.__denote_captured_data.requestBody = {
                    __user: parsedData.__user,
                    __a: parsedData.__a,
                    __hs: parsedData.__hs,
                    dpr: parsedData.dpr,
                    __ccg: parsedData.__ccg,
                    __rev: parsedData.__rev,
                    __hsi: parsedData.__hsi,
                    __dyn: parsedData.__dyn,
                    __csr: parsedData.__csr,
                    fb_dtsg: parsedData.fb_dtsg,
                    jazoest: parsedData.jazoest,
                    lsd: parsedData.lsd,
                    __aaid: parsedData.__aaid,
                    __spin_r: parsedData.__spin_r,
                    __spin_b: parsedData.__spin_b,
                    __spin_t: parsedData.__spin_t,
                    __jssesw: parsedData.__jssesw
                };
            }

            // 处理特定的API请求类型或任何可能包含广告数据的响应
            const targetApiRequests = [
                "AdLibrarySearchPaginationQuery",
                "AdLibraryMobileFocusedStateProviderQuery", 
                "AdLibraryMobileFocusedStateProviderRefetchQuery",
                "AdLibraryFoundationRootQuery"
            ];

            const isTargetApiRequest = hasValidRequestData && 
                parsedData.fb_api_req_friendly_name && 
                targetApiRequests.includes(parsedData.fb_api_req_friendly_name);

            console.log('Checking request type:', {
                hasValidRequestData,
                fb_api_req_friendly_name: parsedData.fb_api_req_friendly_name,
                isTargetApiRequest,
                url: this._url
            });

            // 尝试解析响应数据（对所有Facebook API请求）
            if (this.responseText && this.responseText.length > 0) {
                console.log('Processing response for URL:', this._url);
                let responseData;

                try {
                     // 清理响应文本，移除Facebook的安全前缀
                     let cleanResponseText = this.responseText;
                     if (cleanResponseText.startsWith('for (;;);')) {
                         cleanResponseText = cleanResponseText.substring(9);
                         console.log('Removed Facebook security prefix');
                     }

                     // 处理多行响应（每行都是独立的JSON）
                     const lines = cleanResponseText.split('\n').filter(line => line.trim());
                     console.log('Response has', lines.length, 'lines');

                     for (let i = 0; i < lines.length; i++) {
                         try {
                             let lineText = lines[i].trim();
                             // 再次检查每行是否有安全前缀
                             if (lineText.startsWith('for (;;);')) {
                                 lineText = lineText.substring(9);
                             }

                             const lineData = JSON.parse(lineText);
                             console.log(`Parsed line ${i + 1}:`, Object.keys(lineData));

                             // 检查是否包含广告数据
                             if (containsAdData(lineData)) {
                                 console.log('Found ad data in line', i + 1);
                                 responseData = lineData;
                                 break;
                             }
                         } catch (lineError) {
                             console.log(`Failed to parse line ${i + 1}:`, lineError.message);
                         }
                     }

                     // 如果没有找到广告数据，尝试解析整个响应
                     if (!responseData) {
                         try {
                             responseData = JSON.parse(cleanResponseText);
                             console.log('Parsed entire response as JSON');
                         } catch (fullParseError) {
                             console.log('Failed to parse entire response as JSON:', fullParseError.message);
                             return;
                         }
                     }

                } catch (error) {
                    console.log('Failed to process response:', error.message);
                    return;
                }

                // 验证响应数据结构
                if (!responseData || typeof responseData !== 'object') {
                    console.log('Invalid response data structure');
                    return;
                }

                console.log('Response data structure validated, extracting ads...');

                // 提取广告数据
                let extractedAds = extractAdsFromResponse(responseData);

                if (extractedAds && extractedAds.length > 0) {
                    console.log(`Found ${extractedAds.length} ads in response`);

                    // 更新总数量 - 支持新的API响应数据结构
                    if (responseData.ad_library_main && 
                        responseData.ad_library_main.search_results_connection && 
                        responseData.ad_library_main.search_results_connection.total_count) {
                        window.__denote_captured_data.totalCount = responseData.ad_library_main.search_results_connection.total_count;
                        console.log('Updated total count from ad_library_main:', window.__denote_captured_data.totalCount);
                    }
                    // 兼容旧的数据结构
                    else if (responseData.data && responseData.data.ad_library_main && 
                        responseData.data.ad_library_main.search_results_connection && 
                        responseData.data.ad_library_main.search_results_connection.total_count) {
                        window.__denote_captured_data.totalCount = responseData.data.ad_library_main.search_results_connection.total_count;
                        console.log('Updated total count from data.ad_library_main:', window.__denote_captured_data.totalCount);
                    }

                    // 标准化广告数据字段
                    extractedAds = extractedAds.map(ad => normalizeAdData(ad));


                    // 使用增强的去重算法
                    const newAds = deduplicateAds(extractedAds, window.__denote_captured_data.ads);

                    if (newAds.length > 0) {
                        window.__denote_captured_data.ads.push(...newAds);
                        console.log(`XHR captured ads: ${newAds.length} new ads added. Total: ${window.__denote_captured_data.ads.length}`);

                        // 标记XHR数据获取成功
                        markDataCollected('xhr');
                        
                        // 分发数据更新事件
                        dispatchDataEvent();
                    } else {
                        console.log('XHR: No new ads found (all were duplicates)');
                    }
                } else {
                    console.log('No ads found in response data');
                }
            } else {
                console.log('No response text to process');
            }
        });

        // 调用原始的send方法
        originalSend.apply(this, [data]);
    };

    // ===== 劫持 fetch API（Facebook 可能已切换到 fetch）=====
    window.fetch = async function(input, init) {
        const requestUrl = (typeof input === 'string') ? input : (input.url || input);
        const isAdLibraryPage = location.href.includes("facebook.com/ads/library");
        const isApiRequest =
            requestUrl === "/api/graphql" ||
            requestUrl === "/api/graphql/" ||
            requestUrl.startsWith("/ajax/bz") ||
            requestUrl.includes("/ajax/bootloader") ||
            requestUrl.includes("/api/") ||
            requestUrl.includes("graphql");

        const response = await originalFetch.apply(this, arguments);

        if (!isAdLibraryPage || !isApiRequest) {
            return response;
        }

        try {
            // 克隆响应以避免消费原始响应流
            const clonedResponse = response.clone();
            const text = await clonedResponse.text();

            if (!text || text.length === 0) {
                return response;
            }

            // 清理安全前缀并解析
            let cleanText = text;
            if (cleanText.startsWith('for (;;);')) {
                cleanText = cleanText.substring(9);
            }

            let responseData = null;
            const lines = cleanText.split('\n').filter(line => line.trim());

            for (let i = 0; i < lines.length; i++) {
                try {
                    let lineText = lines[i].trim();
                    if (lineText.startsWith('for (;;);')) {
                        lineText = lineText.substring(9);
                    }
                    const lineData = JSON.parse(lineText);
                    if (containsAdData(lineData)) {
                        responseData = lineData;
                        break;
                    }
                } catch (e) {
                    // 忽略单行解析错误
                }
            }

            if (!responseData) {
                try {
                    responseData = JSON.parse(cleanText);
                } catch (e) {
                    return response;
                }
            }

            if (!responseData || typeof responseData !== 'object') {
                return response;
            }

            let extractedAds = extractAdsFromResponse(responseData);
            if (extractedAds && extractedAds.length > 0) {
                // 更新总数量
                if (responseData.ad_library_main &&
                    responseData.ad_library_main.search_results_connection &&
                    responseData.ad_library_main.search_results_connection.total_count) {
                    window.__denote_captured_data.totalCount = responseData.ad_library_main.search_results_connection.total_count;
                } else if (responseData.data && responseData.data.ad_library_main &&
                    responseData.data.ad_library_main.search_results_connection &&
                    responseData.data.ad_library_main.search_results_connection.total_count) {
                    window.__denote_captured_data.totalCount = responseData.data.ad_library_main.search_results_connection.total_count;
                }

                extractedAds = extractedAds.map(ad => normalizeAdData(ad));
                const newAds = deduplicateAds(extractedAds, window.__denote_captured_data.ads);

                if (newAds.length > 0) {
                    window.__denote_captured_data.ads.push(...newAds);
                    console.log(`Fetch captured ads: ${newAds.length} new ads added. Total: ${window.__denote_captured_data.ads.length}`);
                    markDataCollected('fetch');
                    dispatchDataEvent();
                }
            }
        } catch (err) {
            console.error('Fetch interception error:', err);
        }

        return response;
    };

    // 辅助方法：检查响应是否包含广告数据
    function containsAdData(data) {
        if (!data || typeof data !== 'object') return false;

        // 检查新的API响应数据结构：ad_library_main.search_results_connection
        if (data.ad_library_main &&
            data.ad_library_main.search_results_connection) {
            console.log('Found ad_library_main structure');
            return true;
        }

        // 检查旧的数据结构：data.ad_library_main.search_results_connection
        if (data.data && data.data.ad_library_main &&
            data.data.ad_library_main.search_results_connection) {
            console.log('Found data.ad_library_main structure');
            return true;
        }

        // 检查其他可能的广告数据结构
        if (data.payload && data.payload.data) {
            return containsAdData(data.payload.data);
        }

        return false;
    }

    // 辅助方法：从响应中提取广告数据
    function extractAdsFromResponse(responseData) {
        let ads = [];

        try {
            // 新的API响应数据结构：ad_library_main.search_results_connection.edges[].node.collated_results[]
            if (responseData.ad_library_main && 
                responseData.ad_library_main.search_results_connection &&
                responseData.ad_library_main.search_results_connection.edges) {

                const edges = responseData.ad_library_main.search_results_connection.edges;
                console.log(`Found ${edges.length} edges in ad_library_main structure`);
                
                for (const edge of edges) {
                    if (edge.node && edge.node.collated_results) {
                        console.log(`Processing ${edge.node.collated_results.length} collated results`);
                        ads.push(...edge.node.collated_results);
                    }
                }
            }
            // 兼容旧的data.ad_library_main结构
            else if (responseData.data && responseData.data.ad_library_main &&
                responseData.data.ad_library_main.search_results_connection &&
                responseData.data.ad_library_main.search_results_connection.edges) {

                const edges = responseData.data.ad_library_main.search_results_connection.edges;
                console.log(`Found ${edges.length} edges in data.ad_library_main structure`);
                
                for (const edge of edges) {
                    if (edge.node && edge.node.collated_results) {
                        console.log(`Processing ${edge.node.collated_results.length} collated results`);
                        ads.push(...edge.node.collated_results);
                    }
                }
            }

            // 检查其他可能的数据结构
            if (ads.length === 0 && responseData.payload && responseData.payload.data) {
                return extractAdsFromResponse(responseData.payload.data);
            }

            console.log(`Extracted ${ads.length} ads from response`);

        } catch (error) {
            console.log('Error extracting ads from response:', error.message);
        }

        return ads;
    }

    // 辅助方法：标准化广告数据
    function normalizeAdData(ad) {
        const normalizedAd = { ...ad };

        // 标准化字段名（从下划线转为驼峰命名）
        const fieldMappings = {
            'ad_archive_id': 'adArchiveID',
            'collation_id': 'collationID',
            'end_date': 'endDate',
            'page_id': 'pageID',
            'page_name': 'pageName',
            'start_date': 'startDate',
            'collation_count': 'collationCount'
        };

        for (const [oldKey, newKey] of Object.entries(fieldMappings)) {
            if (normalizedAd.hasOwnProperty(oldKey)) {
                normalizedAd[newKey] = normalizedAd[oldKey];
                delete normalizedAd[oldKey];
            }
        }

        // 确保有 adArchiveID 字段（Facebook API 有时用 id 代替）
        if (!normalizedAd.adArchiveID && normalizedAd.id) {
            normalizedAd.adArchiveID = normalizedAd.id;
        }

        // 确保有ID字段
        if (!normalizedAd.id && normalizedAd.adArchiveID) {
            normalizedAd.id = normalizedAd.adArchiveID;
        }

        return normalizedAd;
    }

    // 增强的数据去重函数
    function deduplicateAds(newAds, existingAds) {
        if (!newAds || newAds.length === 0) return [];
        if (!existingAds || existingAds.length === 0) return newAds;

        // 创建多重索引用于去重
        const existingIndexes = {
            byId: new Set(),
            byAdArchiveId: new Set(),
            byCollationId: new Set(),
            byCompositeKey: new Set()
        };

        // 构建现有广告的索引
        existingAds.forEach(ad => {
            if (ad.id) existingIndexes.byId.add(ad.id);
            if (ad.adArchiveID || ad.ad_archive_id) {
                const archiveId = ad.adArchiveID || ad.ad_archive_id;
                existingIndexes.byAdArchiveId.add(archiveId);
            }
            if (ad.collationID || ad.collation_id) {
                const collationId = ad.collationID || ad.collation_id;
                existingIndexes.byCollationId.add(collationId);
            }
            
            // 创建复合键用于更严格的去重
            const compositeKey = createCompositeKey(ad);
            if (compositeKey) existingIndexes.byCompositeKey.add(compositeKey);
        });

        // 过滤新广告
        const uniqueNewAds = newAds.filter(ad => {
            // 检查各种ID字段
            if (ad.id && existingIndexes.byId.has(ad.id)) return false;
            
            const archiveId = ad.adArchiveID || ad.ad_archive_id;
            if (archiveId && existingIndexes.byAdArchiveId.has(archiveId)) return false;
            
            const collationId = ad.collationID || ad.collation_id;
            if (collationId && existingIndexes.byCollationId.has(collationId)) return false;
            
            // 检查复合键
            const compositeKey = createCompositeKey(ad);
            if (compositeKey && existingIndexes.byCompositeKey.has(compositeKey)) return false;
            
            return true;
        });

        console.log(`Deduplication: ${newAds.length} input ads, ${uniqueNewAds.length} unique ads after filtering`);
        return uniqueNewAds;
    }

    // 创建复合键用于去重
    function createCompositeKey(ad) {
        const parts = [];
        
        // 使用多个字段创建复合键
        if (ad.adArchiveID || ad.ad_archive_id) {
            parts.push(ad.adArchiveID || ad.ad_archive_id);
        }
        if (ad.pageID || ad.page_id) {
            parts.push(ad.pageID || ad.page_id);
        }
        if (ad.startDate || ad.start_date) {
            parts.push(ad.startDate || ad.start_date);
        }
        
        return parts.length > 0 ? parts.join('|') : null;
    }

    console.log('Facebook early interceptor loaded and ready');
    console.log('Data collection state:', window.__denote_data_collection_state);
    console.log('Captured data structure:', window.__denote_captured_data);

    // ===== DOM解析和容错机制 =====

    // 第一种方式： 从document.body中解析广告数据
    async function parseAdsFromBody() {
        // 检查是否应该停止收集
        if (shouldStopCollection()) {
            console.log('Data collection already completed, skipping body parsing');
            return null;
        }

        // 获取配置
        const config = await getExtensionConfig();
        const searchKeyword = config?.dataStructures?.searchResultsConnection || 'search_results_connection';
        const pageInfoKeyword = config?.dataStructures?.pageInfo || 'page_info';

        if (!document.body || !document.body.innerHTML.includes(searchKeyword) ||
            !document.body.innerHTML.includes(pageInfoKeyword)) {
            console.log('Document body does not contain required ad data keywords');
            return null;
        }

        try {
            console.log('Attempting to parse ads from document.body...');
            const bodyContent = document.body.innerHTML;
            const searchResultsIndex = bodyContent.indexOf(`${searchKeyword}":`);
            if (searchResultsIndex === -1) return null;

            const startIndex = searchResultsIndex + `${searchKeyword}":`.length;
            const pageInfoIndex = bodyContent.indexOf(`,"${pageInfoKeyword}`, startIndex);
            if (pageInfoIndex === -1) return null;

            const jsonStr = bodyContent.substring(startIndex, pageInfoIndex) + "}";
            const parsedData = JSON.parse(jsonStr);
            parsedData._source = 'dom'; // 标记数据来源
            console.log('Successfully parsed ads from document.body:', parsedData);
            return parsedData;
        } catch (error) {
            console.log('Failed to parse ads from document.body:', error.message);
            return null;
        }
    }

    // 处理解析到的广告数据
    function processExtractedAds(adsData, source = 'dom') {
        if (!adsData || !adsData.edges) {
            console.log('Invalid ads data structure');
            return;
        }

        console.log(`Processing ${adsData.edges.length} edges from ${source} parsing...`);

        // 提取广告数据 - 处理DOM数据结构
        let extractedAds = [];

        adsData.edges.forEach(edge => {
            if (edge.node && edge.node.collated_results) {
                // DOM数据结构：edge.node.collated_results[]
                edge.node.collated_results.forEach(result => {
                    if (result) {
                        const normalizedAd = normalizeAdData(result);
                        if (normalizedAd) {
                            extractedAds.push(normalizedAd);
                        }
                    }
                });
            } else if (edge.node) {
                // 兼容其他数据结构
                const normalizedAd = normalizeAdData(edge.node);
                if (normalizedAd) {
                    extractedAds.push(normalizedAd);
                }
            }
        });

        if (extractedAds.length > 0) {

            // 使用增强的去重算法
            const newAds = deduplicateAds(processedAds, window.__denote_captured_data.ads);

            if (newAds.length > 0) {
                window.__denote_captured_data.ads.push(...newAds);
                console.log(`${source} parsing captured: ${newAds.length} new ads added. Total: ${window.__denote_captured_data.ads.length}`);

                // 更新总数量 - 支持多种数据结构
                if (adsData.total_count) {
                    window.__denote_captured_data.totalCount = adsData.total_count;
                    console.log('Updated total count from adsData.total_count:', window.__denote_captured_data.totalCount);
                } else if (adsData.count) {
                    window.__denote_captured_data.totalCount = adsData.count;
                    console.log('Updated total count from adsData.count:', window.__denote_captured_data.totalCount);
                } else if (adsData.page_info && adsData.page_info.total_count) {
                    window.__denote_captured_data.totalCount = adsData.page_info.total_count;
                    console.log('Updated total count from adsData.page_info.total_count:', window.__denote_captured_data.totalCount);
                }

                // 标记数据获取成功
                markDataCollected(source);
                
                // 分发数据更新事件
                dispatchDataEvent();
            } else {
                console.log(`${source} parsing: No new ads found (all were duplicates)`);
            }
        } else {
            console.log('DOM parsing: No valid ads found');
        }
    }

    // 容错重试机制
    function initFallbackDataCollection() {
        // 如果已经有数据或应该停止收集，不需要重试
        if (shouldStopCollection() || hasAnyData()) {
            console.log('Data collection already completed or should stop, skipping fallback collection');
            return;
        }

        let retryCount = 0;
        const maxRetries = 5;
        const retryIntervals = [500, 1000, 2000, 3000, 5000]; // 递增间隔
        let retryTimer = null;

        async function attemptDataCollection() {
            console.log(`Fallback data collection attempt ${retryCount + 1}/${maxRetries}`);

            // 如果已经有数据或应该停止收集，停止重试
            if (shouldStopCollection() || hasAnyData()) {
                console.log('Data found via other methods or collection should stop, stopping fallback collection');
                if (retryTimer) {
                    clearTimeout(retryTimer);
                    retryTimer = null;
                }
                return;
            }

            // 尝试从document.body解析
            let adsData = await parseAdsFromBody();

            // 如果找到数据，处理并停止重试
            if (adsData) {
                console.log('Fallback data collection successful!');
                // 确定数据来源
                const dataSource = adsData._source || 'dom';
                processExtractedAds(adsData, dataSource);
                if (retryTimer) {
                    clearTimeout(retryTimer);
                    retryTimer = null;
                }
                return;
            }

            // 增加重试计数
            retryCount++;

            // 如果达到最大重试次数，停止
            if (retryCount >= maxRetries) {
                console.log('Fallback data collection: Maximum retries reached, giving up');
                if (retryTimer) {
                    clearTimeout(retryTimer);
                    retryTimer = null;
                }
                return;
            }

            // 设置下次重试
            const nextInterval = retryIntervals[retryCount];
            console.log(`Scheduling next fallback attempt in ${nextInterval}ms`);
            retryTimer = setTimeout(attemptDataCollection, nextInterval);
        }

        // 开始第一次尝试
        attemptDataCollection();
    }

    // 监听DOM变化，在页面加载完成后启动容错机制
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            console.log('DOM loaded, starting fallback data collection...');
            setTimeout(initFallbackDataCollection, 1000); // 延迟1秒启动
        });
    } else {
        console.log('DOM already loaded, starting fallback data collection...');
        setTimeout(initFallbackDataCollection, 1000); // 延迟1秒启动
    }

    // 也监听页面完全加载
    window.addEventListener('load', function () {
        console.log('Page fully loaded, ensuring fallback data collection is active...');
        setTimeout(initFallbackDataCollection, 2000); // 延迟2秒再次尝试
    });

})();
