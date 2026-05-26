# TapPay

A tap-to-pay mobile wallet for in-person Solana payments. The customer
opens TapPay, taps their phone against the merchant's NFC reader (an
Android device running a companion app), and the transaction is signed
and broadcast in under a second. No QR scanning, no manual amount entry.

The merchant device acts as a Solana Pay request beacon; the customer's
phone reads the encoded amount, recipient, and reference, signs with the
device's secure enclave, and broadcasts via a bundled RPC. End-to-end
confirmation in ~700ms.

We're targeting markets where contactless payments are already normalized
(Latin America, Southeast Asia) but where existing crypto wallets feel
clunky compared to Apple Pay or Google Pay.

Stack: React Native + Expo, Android Host Card Emulation for the merchant
side, Solana Pay reference implementation, secure-enclave signing via
react-native-keychain.
