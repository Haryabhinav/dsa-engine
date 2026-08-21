#include <iostream>
#include <vector>
using namespace std;

int main() {
    long long n, k;
    if (!(cin >> n >> k)) return 0;
    vector<long long> a(n);
    for (long long i = 0; i < n; i++) cin >> a[i];
    long long total = 0;
    for (long long i = 0; i < n; i++)
        for (long long j = 0; j < n; j++)
            if (i <= j && a[i] + a[j] == k) total++;
    cout << total << endl;
    return 0;
}
