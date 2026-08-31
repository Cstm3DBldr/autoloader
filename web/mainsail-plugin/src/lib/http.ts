/**
 * Minimal axios-shaped GET client.
 *
 * The panel only ever issues plain GETs against Moonraker and reads
 * `res.data`, so bundling axios into the plugin would cost ~35 kB to use
 * about fifteen lines of it. This keeps the three existing call sites
 * byte-for-byte unchanged while the plugin stays small.
 *
 * Deliberately narrower than axios: no interceptors, no instances, no
 * request body. If the panel ever needs those, swap this for the real
 * dependency rather than growing this file into a re-implementation.
 */

export interface HttpResponse<T = any> {
    data: T
    status: number
}

export interface HttpGetConfig {
    /** Appended as a query string. Entries that are null/undefined are skipped. */
    params?: Record<string, string | number | boolean | null | undefined>
}

const buildUrl = (url: string, params?: HttpGetConfig['params']): string => {
    if (!params) return url

    const search = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
        if (value === null || value === undefined) return
        search.append(key, String(value))
    })

    const query = search.toString()
    if (!query) return url

    return url + (url.includes('?') ? '&' : '?') + query
}

export const get = async <T = any>(url: string, config: HttpGetConfig = {}): Promise<HttpResponse<T>> => {
    const response = await fetch(buildUrl(url, config.params), {
        method: 'GET',
        headers: { Accept: 'application/json' },
    })

    // axios rejects on a non-2xx status; the call sites rely on that to fall
    // into their catch blocks and reset the list they were filling.
    if (!response.ok) {
        throw new Error(`Request failed with status code ${response.status}`)
    }

    return { data: (await response.json()) as T, status: response.status }
}

export default { get }
