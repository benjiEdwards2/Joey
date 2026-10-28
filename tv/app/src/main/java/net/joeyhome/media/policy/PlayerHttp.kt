package net.joeyhome.media.policy

import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.Request

/**
 * JY-057 (review, 2026-10-27): the HTTP client for every stream, playlist, segment and subtitle request. The member's
 * full Jellyfin token must only ever reach the Jellyfin origin, so:
 * - OkHttp's own redirect following is off. The interceptor follows a redirect itself only when its target is the
 *   Jellyfin origin too (scheme, host and port; at most [MAX_HOPS]), so playlists and segments that bounce inside
 *   Jellyfin still load; a redirect to any other origin is handed back as the 3xx, never requested (the player then
 *   falls back to the Jellyfin app);
 * - the header is added per request, and only when the request's origin is the Jellyfin origin; on any other origin an
 *   `Authorization` header is removed, whoever set it.
 * Pure JVM (OkHttp), tested against two local servers in PlayerHttpTest.
 */
object PlayerHttp {
    const val HEADER = "Authorization"
    const val MAX_HOPS = 5

    fun client(jellyfin: Origin, authorization: String, connectMs: Long = 15_000, readMs: Long = 30_000): OkHttpClient =
        OkHttpClient.Builder()
            .followRedirects(false)
            .followSslRedirects(false)
            .connectTimeout(connectMs, TimeUnit.MILLISECONDS)
            .readTimeout(readMs, TimeUnit.MILLISECONDS)
            .addInterceptor { chain ->
                fun guarded(request: Request): Request =
                    if (Origin.of(request.url.toString()) == jellyfin) {
                        request.newBuilder().header(HEADER, authorization).build()
                    } else {
                        request.newBuilder().removeHeader(HEADER).build()
                    }
                var request = guarded(chain.request())
                var response = chain.proceed(request)
                var hops = 0
                while (response.isRedirect && hops < MAX_HOPS) {
                    val next = response.header("Location")?.let { response.request.url.resolve(it) } ?: break
                    if (Origin.of(next.toString()) != jellyfin) break   // never follow off the Jellyfin origin
                    response.close()
                    val method = if (response.code == 303) "GET" else request.method
                    request = guarded(request.newBuilder().url(next).method(method, if (method == "GET") null else request.body).build())
                    response = chain.proceed(request)
                    hops++
                }
                response
            }
            .build()
}
