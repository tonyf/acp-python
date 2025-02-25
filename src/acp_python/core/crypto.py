import os
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from typing import Tuple


def generate_keys() -> Tuple[x25519.X25519PrivateKey, bytes]:
    """
    Generates a pair of ephemeral private and public keys for key exchange.

    Returns:
        A tuple containing (private_key, public_key_bytes)
    """
    # Generate a private key
    private_key = x25519.X25519PrivateKey.generate()

    # Compute the public key
    public_key = private_key.public_key()
    public_key_bytes = public_key.public_bytes_raw()

    return private_key, public_key_bytes


def compute_shared_secret(
    private_key: x25519.X25519PrivateKey, peer_public_key: bytes
) -> bytes:
    """
    Computes a shared secret using our private key and a peer's public key.

    Args:
        private_key: Our X25519 private key
        peer_public_key: The peer's public key bytes

    Returns:
        The computed shared secret as bytes
    """
    # Convert peer's public key bytes to a public key object
    peer_public_key_obj = x25519.X25519PublicKey.from_public_bytes(peer_public_key)

    # Compute the shared secret
    shared_secret = private_key.exchange(peer_public_key_obj)

    return shared_secret


def decrypt_message(shared_secret: bytes, encrypted_message: bytes) -> bytes:
    """
    Decrypts an encrypted message using a shared secret key.

    Args:
        shared_secret: The 32-byte shared secret key used for decryption
        encrypted_message: The encrypted message with a 12-byte nonce prepended

    Returns:
        The decrypted message as bytes

    Raises:
        ValueError: If the encrypted message is too short or decryption fails
    """
    # Check that the encrypted message is long enough to contain a nonce
    NONCE_LEN = 12
    if len(encrypted_message) < NONCE_LEN:
        raise ValueError("Encrypted message is too short")

    # Extract the nonce from the beginning of the encrypted message
    nonce = encrypted_message[:NONCE_LEN]
    ciphertext = encrypted_message[NONCE_LEN:]

    # Create an AESGCM cipher with the shared secret
    cipher = AESGCM(shared_secret)

    # Decrypt the data using the nonce and ciphertext
    try:
        plaintext = cipher.decrypt(nonce, ciphertext, None)
        return plaintext
    except Exception as e:
        raise ValueError(f"Decryption failed: {str(e)}")


def encrypt_message(shared_secret: bytes, plaintext: bytes) -> bytes:
    """
    Encrypts a message using a shared secret key.

    Args:
        shared_secret: The 32-byte shared secret key used for encryption
        plaintext: The message to encrypt

    Returns:
        The encrypted message with a 12-byte nonce prepended
    """
    # Generate a random 12-byte nonce
    nonce = os.urandom(12)

    # Create an AESGCM cipher with the shared secret
    cipher = AESGCM(shared_secret)

    # Encrypt the data using the nonce
    ciphertext = cipher.encrypt(nonce, plaintext, None)

    # Prepend the nonce to the ciphertext
    return nonce + ciphertext
