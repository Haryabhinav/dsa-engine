#include <iostream>
#include <vector>
#include <unordered_map>
using namespace std;

int main() {
    long long n, k;
    if (!(cin >> n >> k)) return 0;
    vector<long long> a(n);
    for (long long i = 0; i < n; i++) cin >> a[i];
    unordered_map<long long, long long> seen;
    long long total = 0;
    for (long long i = 0; i < n; i++) {
        total += seen[k - a[i]];
        seen[a[i]]++;
    }
    cout << total << endl;
    return 0;
}
