package net.joeyhome.media.policy

import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient

/**
 * JY-057 (review, 2026-10-27): the HTTP client for every stream, playlist, segment and subtitle request. The member's
 * full Jellyfin token must only ever reach the Jellyfin origin, so:
 * - redirects are off (plain and cross-protocol): a 3xx is an answer, never followed, so no request with the header can
 *   land on another host (Jellyfin's streams do not redirect; a redirect ends playback and the fallback hands off);
 * - the header is added by an interceptor per request, and only when the request's origin is the Jellyfin origin; on
 *   any other origin an `Authorization` header is removed, whoever set it.
 * Pure JVM (OkHttp), tested against two local servers in PlayerHttpTest.
 */
object PlayerHttp {
    const val HEADER = "Authorization"

    fun client(jellyfin: Origin, authorization: String, connectMs: Long = 15_000, readMs: Long = 30_000): OkHttpClient =
        OkHttpClient.Builder()
            .followRedirects(false)
            .followSslRedirects(false)
            .connectTimeout(connectMs, TimeUnit.MILLISECONDS)
            .readTimeout(readMs, TimeUnit.MILLISECONDS)
            .addInterceptor { chain ->
                val request = chain.request()
                val onJellyfin = Origin.of(request.url.toString()) == jellyfin
                val out = if (onJellyfin) {
                    request.newBuilder().header(HEADER, authorization).build()
                } else {
                    request.newBuilder().removeHeader(HEADER).build()
                }
                chain.proceed(out)
            }
            .build()
}
