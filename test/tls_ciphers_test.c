/* TLS 1.3 cipher configuration and negotiated restriction tests. */
#include <usual/tls/tls.h>
#include <usual/string.h>

#ifdef USUAL_LIBSSL_FOR_TLS
#include <usual/tls/tls_internal.h>
#include <openssl/err.h>

#define AES128 "TLS_AES_128_GCM_SHA256"
#define AES256 "TLS_AES_256_GCM_SHA384"
#define CHACHA "TLS_CHACHA20_POLY1305_SHA256"

static SSL_CTX *configure(const char *ciphers, bool success)
{
	struct tls ctx = {0};
	struct tls_config config = {0};
	int ret;

	ctx.ssl_ctx = SSL_CTX_new(TLS_method());
	if (!ctx.ssl_ctx)
		abort();
	config.protocols = TLS_PROTOCOL_TLSv1_3;
	config.verify_time = 1;
	config.cipher_suites = (char *)ciphers;
	ctx.config = &config;
	ret = tls_configure_ssl(&ctx);
	if ((ret == 0) != success || (ret != 0 && ctx.error.msg == NULL)) {
		fprintf(stderr, "unexpected configuration result for %s: %s\n",
			ciphers ? ciphers : "(default)", ctx.error.msg ? ctx.error.msg : "success");
		abort();
	}
	free(ctx.error.msg);
	return ctx.ssl_ctx;
}

#if !defined(OPENSSL_IS_BORINGSSL) || defined(HAVE_SSL_CTX_SET1_TLS13_CIPHERS)
static void handshake(const char *client_ciphers, const char *server_ciphers,
		      const char *expected, bool success)
{
	SSL_CTX *client_ctx = configure(client_ciphers, true);
	SSL_CTX *server_ctx = configure(server_ciphers, true);
	SSL *client, *server;
	struct tls client_state = {0}, server_state = {0};
	BIO *client_bio, *server_bio;
	int i, j, ret, err;
	bool complete = false, failed = false;
	SSL *peers[2];

	if (SSL_CTX_use_certificate_chain_file(server_ctx, "../lib/test/ssl/ca1_server1.crt") != 1 ||
	    SSL_CTX_use_PrivateKey_file(server_ctx, "../lib/test/ssl/ca1_server1.key", SSL_FILETYPE_PEM) != 1)
		abort();
	SSL_CTX_set_options(server_ctx, SSL_OP_CIPHER_SERVER_PREFERENCE);
	client = SSL_new(client_ctx);
	server = SSL_new(server_ctx);
	if (!client || !server || BIO_new_bio_pair(&client_bio, 0, &server_bio, 0) != 1)
		abort();
	if (SSL_set_app_data(client, &client_state) != 1 ||
	    SSL_set_app_data(server, &server_state) != 1)
		abort();
	SSL_set_bio(client, client_bio, client_bio);
	SSL_set_bio(server, server_bio, server_bio);
	SSL_set_connect_state(client);
	SSL_set_accept_state(server);
	peers[0] = client;
	peers[1] = server;
	for (i = 0; i < 100 && !failed; i++) {
		for (j = 0; j < 2; j++) {
			ERR_clear_error();
			ret = SSL_do_handshake(peers[j]);
			if (ret == 1)
				continue;
			err = SSL_get_error(peers[j], ret);
			if (err != SSL_ERROR_WANT_READ && err != SSL_ERROR_WANT_WRITE)
				failed = true;
		}
		if (SSL_is_init_finished(client) && SSL_is_init_finished(server)) {
			complete = true;
			break;
		}
	}
	if (complete != success || (!success && !failed))
		abort();
	if (complete && expected &&
	    (strcmp(SSL_get_cipher(client), expected) != 0 || strcmp(SSL_get_cipher(server), expected) != 0))
		abort();
	SSL_free(client);
	SSL_free(server);
	SSL_CTX_free(client_ctx);
	SSL_CTX_free(server_ctx);
}
#endif
#endif

int main(void)
{
#ifdef USUAL_LIBSSL_FOR_TLS
	if (tls_init() != 0)
		abort();
	SSL_CTX_free(configure(NULL, true));
	SSL_CTX_free(configure("", true));
#if defined(OPENSSL_IS_BORINGSSL) && !defined(HAVE_SSL_CTX_SET1_TLS13_CIPHERS)
	SSL_CTX_free(configure(AES128, false));
#else
	/* Both sides enforce restrictions; non-overlapping lists must fail. */
	handshake(NULL, NULL, NULL, true);
	handshake("", "", NULL, true);
	handshake(AES128, AES128, AES128, true);
	handshake(AES256, AES256, AES256, true);
	handshake(CHACHA, CHACHA, CHACHA, true);
	handshake(AES128, CHACHA, NULL, false);
	handshake(AES128 ":" CHACHA, CHACHA ":" AES128, CHACHA, true);
	handshake(AES128 ":" AES128 ":" CHACHA, AES128, AES128, true);
	SSL_CTX_free(configure("NOT_A_CIPHER", false));
#ifdef OPENSSL_IS_BORINGSSL
	/* Invalid input must never become BoringSSL's default cipher list. */
	SSL_CTX_free(configure(":", false));
	SSL_CTX_free(configure(":" AES128, false));
	SSL_CTX_free(configure(AES128 ":", false));
	SSL_CTX_free(configure(AES128 "::" CHACHA, false));
	SSL_CTX_free(configure(AES128 ":NOT_A_CIPHER", false));
	/* Pre-TLS-1.3 suites must not be accepted as TLS 1.3 suites. */
	SSL_CTX_free(configure("TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256", false));
#endif
#endif
	tls_deinit();
#endif
	return 0;
}
